from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import httpx
import json

app = FastAPI()
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_clients = []
current_leader_url = None

# Replicas network addresses from docker-compose
REPLICA_URLS = [
    "http://replica1:8001",
    "http://replica2:8002",
    "http://replica3:8003",
    "http://replica4:8004"
]

@app.on_event("startup")
async def startup_event():
    # Start a background task to constantly monitor who the leader is
    asyncio.create_task(find_leader_loop())

async def find_leader_loop():
    global current_leader_url
    async with httpx.AsyncClient() as client:
        while True:
            found_leader = False
            for url in REPLICA_URLS:
                try:
                    response = await client.get(f"{url}/status", timeout=0.5)
                    if response.status_code == 200:
                        data = response.json()
                        if data["state"] == "LEADER":
                            if current_leader_url != url:
                                print(f"Gateway: New Leader detected at {url}")
                            current_leader_url = url
                            found_leader = True
                            break
                except Exception:
                    continue
            
            if not found_leader:
                current_leader_url = None
                
            await asyncio.sleep(1) # Check every 1 second

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    
    try:
        async with httpx.AsyncClient() as client:
            # --- NEW: INITIAL CLIENT SYNC ---
            # When a new user joins, fetch the current canvas state from the Leader
            if current_leader_url:
                try:
                    res = await client.get(f"{current_leader_url}/log", timeout=1.0)
                    if res.status_code == 200:
                        history = res.json().get("log", [])
                        # Send the entire history as a special "sync" array
                        await websocket.send_text(json.dumps({"type": "sync", "data": history}))
                except Exception as e:
                    print(f"Gateway: Failed to fetch initial log: {e}")
            # --------------------------------

            # Normal real-time listening loop
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)

                # Forward to the RAFT Leader
                if current_leader_url:
                    try:
                        if message.get('type') in ['stroke', 'undo', 'redo']:
                            # Handle strokes and undo/redo commands
                            res = await client.post(f"{current_leader_url}/stroke", json=message)
                            if res.status_code == 200 and "success" in res.json():
                                # Once Leader accepts it, broadcast to all clients
                                for client_ws in connected_clients:
                                    if client_ws != websocket:
                                        await client_ws.send_text(data)
                        else:
                            # Legacy stroke format (for backward compatibility)
                            res = await client.post(f"{current_leader_url}/stroke", json=message)
                            if res.status_code == 200 and "success" in res.json():
                                # Once Leader accepts it, broadcast to all clients
                                for client_ws in connected_clients:
                                    if client_ws != websocket:
                                        await client_ws.send_text(data)
                    except Exception as e:
                        pass
                else:
                    print("Gateway: Message dropped, no leader available.")
                    
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        connected_clients.remove(websocket)

@app.get("/cluster-status")
async def get_cluster_status():
    if current_leader_url:
        return {"leader": current_leader_url, "status": "Healthy"}
    return {"leader": "None", "status": "Searching for quorum..."}

@app.get("/cluster-info")
async def get_cluster_info():
    """Returns detailed status of every replica for the dashboard."""
    replicas = []
    async with httpx.AsyncClient() as client:
        for url in REPLICA_URLS:
            try:
                response = await client.get(f"{url}/status", timeout=0.5)
                if response.status_code == 200:
                    data = response.json()
                    replicas.append({
                        "id": data.get("id"),
                        "url": url,
                        "state": data.get("state"),
                        "term": data.get("term"),
                        "log_size": data.get("log_size"),
                        "alive": True
                    })
                else:
                    replicas.append({"url": url, "alive": False})
            except Exception:
                replicas.append({"url": url, "alive": False})

    leader_info = None
    for r in replicas:
        if r.get("state") == "LEADER":
            leader_info = r
            break

    return {
        "leader": leader_info,
        "replicas": replicas
    }