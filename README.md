# Distributed Real-Time Drawing Board with Mini-RAFT Consensus

A cloud-native, fault-tolerant real-time collaboration application built to demonstrate distributed systems consensus. This project implements a custom Mini-RAFT algorithm to maintain a synchronized, append-only log of drawing strokes across a 3-node containerized cluster.

**PES University | Department of Computer Science**
* **Developer:** Tarun M Gowda (PES1UG23CS639), Tarun Harithas (PES1UG23CS640), Syed Aman Sohrab (PES1UG23CS626), Swayam Shah (PES1UG23CS625)
* Developed as part of a 4-person engineering team.

---

## 🚀 Features

* **Real-Time Collaboration:** HTML5 Canvas state synchronized instantly across multiple clients using WebSockets.
* **Mini-RAFT Consensus:** Custom implementation of Leader Election and Log Replication.
* **High Availability:** 3-node backend cluster capable of surviving single-node failures without dropping client connections.
* **Zero-Downtime Hot-Reloading:** Source code modifications trigger graceful container restarts via Docker bind-mounts while the cluster maintains quorum.
* **Catch-Up Protocol:** Restarted or lagging nodes automatically request and download missing drawing history from the active Leader.

## 🏗️ System Architecture

The infrastructure consists of two primary layers connected via a shared Docker network:

1. **Gateway Service (FastAPI / WebSockets):** Acts as the ingress router. It maintains WebSocket connections with clients, continuously polls the backend cluster to discover the current Leader, and routes all incoming drawing strokes strictly to that Leader.
2. **Replica Cluster (3x Python Nodes):** The stateful database layer. Nodes cycle through `FOLLOWER`, `CANDIDATE`, and `LEADER` states. The Leader replicates logs via background `/append-entries` heartbeats sent every 150ms.

## 🛠️ Technology Stack

* **Backend:** Python 3.10, FastAPI, Uvicorn, HTTPX (Async RPCs)
* **Frontend:** Vanilla JavaScript, HTML5 Canvas, WebSockets
* **Infrastructure:** Docker, Docker Compose

## 🚦 Getting Started

### Prerequisites
* Docker and Docker Compose installed on your machine.

### Installation & Execution
1. Clone the repository:
   ```bash
   git clone [https://github.com/yourusername/miniraft-drawing-board.git](https://github.com/yourusername/miniraft-drawing-board.git)
   cd miniraft-drawing-board
   ```
2. Build and launch the cluster:
   ```bash
   docker-compose up --build
   ```
3. Open a browser and navigate to: `http://localhost:8080/frontend/index.html` (Or directly open the `index.html` file in multiple browser tabs).

## 🧪 Chaos Testing & Failover

To observe the fault tolerance of the Mini-RAFT implementation:

1. Open two browser tabs and draw on the canvas.
2. Watch the terminal logs to identify the current Leader (e.g., `Node 2`).
3. Open a new terminal and intentionally kill the Leader container:
   ```bash
   docker stop miniraft-replica2-1
   ```
4. **Observe:** The remaining two nodes will time out, hold an election, and declare a new Leader within 800ms. 
5. Continue drawing in the browser; the Gateway will automatically route to the new Leader without dropping the WebSocket connection.
6. Restart the dead container:
   ```bash
   docker start miniraft-replica2-1
   ```
7. **Observe:** The restarted node will rejoin as a Follower, report an empty log length, and the active Leader will immediately sync the missing drawing history to it.
