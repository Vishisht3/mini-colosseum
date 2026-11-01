/**
 * Electron Preload script for secure desktop integration.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  isElectron: true,
  platform: process.platform,
  saveKeychainKey: (key) => ipcRenderer.invoke("keychain:set", key),
  getKeychainKey: () => ipcRenderer.invoke("keychain:get"),
});
