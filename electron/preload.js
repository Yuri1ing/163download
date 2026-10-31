'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// 渲染进程只拿到这三个窗口动作 + 一个标记位，其余一切走本地 HTTP 后端
contextBridge.exposeInMainWorld('ncmWin', {
  isElectron: true,
  minimize: () => ipcRenderer.invoke('win:minimize'),
  toggleMax: () => ipcRenderer.invoke('win:toggleMax'),
  close: () => ipcRenderer.invoke('win:close'),
});

window.addEventListener('DOMContentLoaded', () => {
  document.documentElement.classList.add('is-electron');
});
