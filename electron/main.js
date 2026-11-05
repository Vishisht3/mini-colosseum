/**
 * Mini-Colosseum Desktop Electron Main Process
 * Implements Section 5 of Mini Colosseum Final Specification:
 * - Creates a random per-launch session token (Section 5.2)
 * - Starts the backend on a free port, reading the one-line JSON handshake (Section 5.1)
 * - Polls /health every 250ms for up to 30s before opening the window
 * - Context isolation enabled, Node integration disabled (Section 5.2)
 * - On quit sends POST /shutdown, waits 3s, then terminates the whole process tree (Section 5.1)
 */

const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const { spawn, execSync } = require("child_process");
const http = require("http");
const crypto = require("crypto");

let mainWindow = null;
let pythonProcess = null;
let backendPort = 8765;
let backendUrl = `http://127.0.0.1:${backendPort}`;
const sessionToken = crypto.randomBytes(24).toString("hex");
process.env.MINI_COLOSSEUM_SESSION_TOKEN = sessionToken;

function resolvePythonCommand(rootDir) {
  if (app.isPackaged) {
    return path.join(rootDir, "backend", process.platform === "win32" ? "colosseum-backend.exe" : "colosseum-backend");
  }
  if (process.platform === "win32") {
    const candidates = [
      "python",
      "py",
      path.join(process.env.LOCALAPPDATA || "", "Python", "bin", "python.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Programs", "Python", "Python314", "python.exe"),
    ];
    for (const cand of candidates) {
      try {
        execSync(`"${cand}" --version`, { stdio: "ignore" });
        return cand;
      } catch (_) {}
    }
    return "python";
  }
  return "python3";
}

function startPythonBackend(onReadyCallback) {
  const rootDir = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
  const pythonCmd = resolvePythonCommand(rootDir);
  const pythonArgs = app.isPackaged
    ? ["0", "--token", sessionToken]
    : ["-m", "backend.main", "0", "--token", sessionToken];
  console.log(`Starting Python backend using '${pythonCmd}' from ${rootDir}...`);

  const spawnOpts = {
    cwd: rootDir,
    env: { ...process.env, PYTHONUNBUFFERED: "1", MINI_COLOSSEUM_SESSION_TOKEN: sessionToken },
  };
  if (process.platform !== "win32") {
    spawnOpts.detached = true;
  }

  pythonProcess = spawn(
    pythonCmd,
    pythonArgs,
    spawnOpts,
  );

  let handshakeReceived = false;

  pythonProcess.stdout.on("data", (data) => {
    const text = data.toString();
    console.log(`[Python Backend]: ${text.trim()}`);

    // Section 5.1: The backend prints the port as one JSON line
    if (!handshakeReceived) {
      const lines = text.split(/\r?\n/);
      for (const line of lines) {
        try {
          const parsed = JSON.parse(line.trim());
          if (parsed.status === "ready" && parsed.port) {
            backendPort = parsed.port;
            backendUrl = `http://127.0.0.1:${backendPort}`;
            handshakeReceived = true;
            console.log(`Handshake parsed! Backend port: ${backendPort}`);
            if (onReadyCallback) onReadyCallback();
            break;
          }
        } catch (_) {}
      }
    }
  });

  pythonProcess.stderr.on("data", (data) => {
    console.error(`[Python Backend Error]: ${data.toString().trim()}`);
  });

  pythonProcess.on("close", (code) => {
    console.log(`Python backend exited with code ${code}`);
  });

  pythonProcess.on("error", (err) => {
    console.error(`Failed to start Python backend: ${err.message}`);
    dialog.showErrorBox(
      "Backend Launch Error",
      `Could not start the Python backend process.\n\n${err.message}\n\nPlease ensure Python is installed and accessible.`
    );
  });
}

function pollBackendReady(callback, retries = 120) {
  if (retries <= 0) {
    console.error("Backend failed to start in time (30s timeout).");
    callback(false);
    return;
  }

  const req = http.get(`${backendUrl}/health?token=${sessionToken}`, (res) => {
    if (res.statusCode === 200) {
      callback(true);
    } else {
      setTimeout(() => pollBackendReady(callback, retries - 1), 250);
    }
  });

  req.on("error", () => {
    setTimeout(() => pollBackendReady(callback, retries - 1), 250);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    title: "RocqIde - [proof.v] - Mini-Colosseum Research Harness v2.0",
    backgroundColor: "#dedcd7",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(`${backendUrl}/?token=${sessionToken}`);

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function killProcessTree(pid) {
  if (!pid) return;
  try {
    if (process.platform === "win32") {
      execSync(`taskkill /pid ${pid} /T /F`);
    } else {
      process.kill(-pid, "SIGKILL");
    }
  } catch (e) {
    try {
      if (pythonProcess) pythonProcess.kill("SIGTERM");
    } catch (_) {}
  }
}

// IPC Handlers for preload.js (Section 5.2)
ipcMain.handle("dialog:open", async (_, opts) => {
  return await dialog.showOpenDialog(mainWindow, opts || {});
});

ipcMain.handle("dialog:save", async (_, opts) => {
  return await dialog.showSaveDialog(mainWindow, opts || {});
});

ipcMain.handle("app:quit", () => {
  app.quit();
});

app.whenReady().then(() => {
  startPythonBackend(() => {
    pollBackendReady((ready) => {
      if (ready) {
        createWindow();
      } else {
        dialog.showErrorBox(
          "Backend Connection Error",
          `Could not connect to the Python orchestrator on ${backendUrl} within 30 seconds.`
        );
      }
    });
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

let shutdownSent = false;
app.on("before-quit", (event) => {
  if (shutdownSent) return;
  shutdownSent = true;
  event.preventDefault();

  console.log("Sending POST /shutdown to backend...");
  const postData = JSON.stringify({});
  const req = http.request(
    `${backendUrl}/shutdown`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Session-Token": sessionToken,
      },
    },
    () => {}
  );
  req.on("error", () => {});
  req.write(postData);
  req.end();

  // Wait 3 seconds, then kill whole process tree (Section 5.1)
  setTimeout(() => {
    if (pythonProcess && pythonProcess.pid) {
      console.log("Shutting down Python orchestrator process tree...");
      killProcessTree(pythonProcess.pid);
    }
    app.exit(0);
  }, 3000);
});
