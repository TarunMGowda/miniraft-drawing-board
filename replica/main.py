from fastapi import FastAPI
from pydantic import BaseModel
import asyncio
import httpx
import random
import time
import os

app = FastAPI()

# --- 1. CONFIGURATION & PEER DISCOVERY ---
REPLICA_ID = int(os.getenv("REPLICA_ID", 1))
PORT = int(os.getenv("PORT", 8001))

ALL_REPLICAS = {
    1: "http://replica1:8001",
    2: "http://replica2:8002",
    3: "http://replica3:8003",
    4: "http://replica4:8004"
}
PEERS = {id: url for id, url in ALL_REPLICAS.items() if id != REPLICA_ID}

# --- 2. RAFT NODE STATE ---
class RaftState:
    FOLLOWER = "FOLLOWER"
    CANDIDATE = "CANDIDATE"
    LEADER = "LEADER"

class Node:
    def __init__(self):
        self.state = RaftState.FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.log = [] # This stores all our drawing strokes!
        
        self.last_heartbeat = time.time()
        self.election_timeout = random.uniform(0.5, 0.8)

node = Node()

# --- 3. RPC PAYLOAD MODELS ---
class VoteRequest(BaseModel):
    term: int
    candidate_id: int
    last_log_index: int
    last_log_term: int

class VoteResponse(BaseModel):
    term: int
    vote_granted: bool

class AppendEntriesRequest(BaseModel):
    term: int
    leader_id: int
    prev_log_index: int
    prev_log_term: int
    entries: list  
    leader_commit: int

class AppendEntriesResponse(BaseModel):
    term: int
    success: bool
    log_length: int # Added so the leader knows if we are falling behind!

class SyncLogRequest(BaseModel):
    entries: list

# --- 4. THE BACKGROUND LOOPS ---
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(election_timer_loop())
    asyncio.create_task(heartbeat_loop())

async def election_timer_loop():
    while True:
        await asyncio.sleep(0.05) 
        
        if node.state == RaftState.LEADER:
            continue
            
        now = time.time()
        if (now - node.last_heartbeat) > node.election_timeout:
            print(f"Node {REPLICA_ID}: Election timeout! Becoming CANDIDATE.")
            await start_election()

async def heartbeat_loop():
    while True:
        await asyncio.sleep(0.15) 
        
        if node.state != RaftState.LEADER:
            continue
            
        async with httpx.AsyncClient() as client:
            for peer_id, peer_url in PEERS.items():
                try:
                    payload = AppendEntriesRequest(
                        term=node.current_term,
                        leader_id=REPLICA_ID,
                        prev_log_index=len(node.log) - 1,
                        prev_log_term=0, 
                        entries=[],      
                        leader_commit=0  
                    ).dict()
                    
                    response = await client.post(f"{peer_url}/append-entries", json=payload, timeout=0.2)
                    
                    # LOGIC ADDED: If the follower replies "success=False", they are missing logs!
                    if response.status_code == 200:
                        data = response.json()
                        if not data["success"] and data["log_length"] < len(node.log):
                            # The Catch-Up Protocol! Send them the strokes they missed.
                            missing_entries = node.log[data["log_length"]:]
                            print(f"Node {REPLICA_ID} (Leader): Node {peer_id} is behind. Syncing {len(missing_entries)} logs...")
                            await client.post(f"{peer_url}/sync-log", json={"entries": missing_entries}, timeout=0.5)

                except Exception:
                    pass 

async def start_election():
    node.state = RaftState.CANDIDATE
    node.current_term += 1
    node.voted_for = REPLICA_ID 
    node.last_heartbeat = time.time() 
    node.election_timeout = random.uniform(0.5, 0.8) 
    
    votes_received = 1 
    
    async with httpx.AsyncClient() as client:
        for peer_id, peer_url in PEERS.items():
            try:
                payload = VoteRequest(
                    term=node.current_term,
                    candidate_id=REPLICA_ID,
                    last_log_index=len(node.log) - 1,
                    last_log_term=0 
                ).dict()
                
                response = await client.post(f"{peer_url}/request-vote", json=payload, timeout=0.2)
                if response.status_code == 200 and response.json().get("vote_granted"):
                    votes_received += 1
            except Exception:
                pass

    if votes_received >= 3 and node.state == RaftState.CANDIDATE:
        print(f"\n🏆 Node {REPLICA_ID} WON THE ELECTION! Now LEADER for Term {node.current_term} 🏆\n")
        node.state = RaftState.LEADER

# --- 5. THE RPC ENDPOINTS ---
@app.post("/request-vote", response_model=VoteResponse)
async def request_vote(req: VoteRequest):
    if req.term < node.current_term:
        return VoteResponse(term=node.current_term, vote_granted=False)
        
    if req.term > node.current_term:
        node.current_term = req.term
        node.state = RaftState.FOLLOWER
        node.voted_for = None
        
    if node.voted_for is None or node.voted_for == req.candidate_id:
        node.voted_for = req.candidate_id
        node.last_heartbeat = time.time() 
        return VoteResponse(term=node.current_term, vote_granted=True)
        
    return VoteResponse(term=node.current_term, vote_granted=False)

@app.post("/append-entries", response_model=AppendEntriesResponse)
async def append_entries(req: AppendEntriesRequest):
    if req.term < node.current_term:
        return AppendEntriesResponse(term=node.current_term, success=False, log_length=len(node.log))
        
    if req.term >= node.current_term:
        node.current_term = req.term
        node.state = RaftState.FOLLOWER
        node.voted_for = None
        node.last_heartbeat = time.time()
        
    # Check if we are missing logs compared to the leader!
    if req.prev_log_index > len(node.log) - 1:
        return AppendEntriesResponse(term=node.current_term, success=False, log_length=len(node.log))
        
    return AppendEntriesResponse(term=node.current_term, success=True, log_length=len(node.log))

@app.post("/sync-log")
async def sync_log(req: SyncLogRequest):
    # This is called by the Leader to catch us up!
    node.log.extend(req.entries)
    print(f"Node {REPLICA_ID}: Synced {len(req.entries)} new strokes! Total log size: {len(node.log)}")
    return {"success": True}

@app.get("/status")
async def get_status():
    return {"id": REPLICA_ID, "state": node.state, "term": node.current_term, "log_size": len(node.log)}

@app.post("/stroke")
async def receive_stroke(stroke: dict):
    if node.state != RaftState.LEADER:
        return {"error": "Not the leader"}
    
    node.log.append(stroke)
    return {"success": True, "stroke": stroke}

@app.get("/log")
async def get_log():
    # Return the entire drawing history for new clients
    return {"log": node.log}