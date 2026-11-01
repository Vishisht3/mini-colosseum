/**
 * Mini-Colosseum Desktop Electron Main Process
 * Based on Section 7 & Section 13.2 of Mini-Colosseum Specification v1.0.
 * Automatically starts the Python orchestrator as a child process on launch
 * and shuts it down on exit.
 */

const { app, BrowserWindow, Menu, ipcMain, dialog } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

let mainWindow = null;
let pythonProcess = null;
const BACKEND_PORT = 8765;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

function startPythonBackend() {
  const rootDir = path.resolve(__dirname, "..");
  console.log(`Starting Python backend from ${rootDir}...`);

  pythonProcess = spawn("python3", ["-m", "backend.main", String(BACKEND_PORT)], {
    cwd: rootDir,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[Python Backend]: ${data.toString().trim()}`);
  });

  pythonProcess.stderr.on("data", (data) => {
    console.error(`[Python Backend Error]: ${data.toString().trim()}`);
  });

  pythonProcess.on("close", (code) => {
    console.log(`Python backend exited with code ${code}`);
  });
}

function pollBackendReady(callback, retries = 30) {
  if (retries <= 0) {
    console.error("Backend failed to start in time.");
    callback(false);
    return;
  }

  const req = http.get(`${BACKEND_URL}/api/settings`, (res) => {
    if (res.statusCode === 200) {
      callback(true);
    } else {
      setTimeout(() => pollBackendReady(callback, retries - 1), 500);
    }
  });

  req.on("error", () => {
    setTimeout(() => pollBackendReady(callback, retries - 1), 500);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1340,
    height: 880,
    minWidth: 900,
    minHeight: 600,
    title: "Mini-Colosseum | Research-Harness Workbench",
    backgroundColor: "#f4f4f0",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(BACKEND_URL);

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  startPythonBackend();

  pollBackendReady((ready) => {
    if (ready) {
      createWindow();
    } else {
      dialog.showErrorBox(
        "Backend Connection Error",
        "Could not connect to the Python orchestrator on localhost:8765."
      );
    }
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

app.on("will-quit", () => {
  if (pythonProcess) {
    console.log("Shutting down Python orchestrator child process...");
    pythonProcess.kill("SIGTERM");
  }
});
