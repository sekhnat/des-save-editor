'use strict';
// Desktop shell for des_editor.html. The page is the application; this file only
// hosts it in a locked-down window. No preload script and no IPC.
const { app, BrowserWindow, Menu, dialog, session } = require('electron');
const path = require('path');

const PAGE = app.isPackaged
  ? path.join(process.resourcesPath, 'des_editor.html')
  : path.join(__dirname, '..', 'des_editor.html');

const ALLOWED_PERMISSIONS = new Set(['fileSystem', 'clipboard-sanitized-write']);
const ALLOWED_SCHEMES = ['file:', 'blob:', 'data:', 'devtools:'];

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    backgroundColor: '#0d0f12',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });

  win.webContents.on('will-navigate', (event) => event.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

  // Electron silently cancels a close that the page's beforeunload guard blocks.
  win.webContents.on('will-prevent-unload', (event) => {
    const choice = dialog.showMessageBoxSync(win, {
      type: 'warning',
      buttons: ['Quit', 'Cancel'],
      defaultId: 1,
      cancelId: 1,
      title: 'Unexported edits',
      message: 'Discard unexported edits and quit?',
      detail: 'Edits that were not exported with Save file or Save all (ZIP) will be lost.',
    });
    if (choice === 0) event.preventDefault();
  });

  win.loadFile(PAGE);
  return win;
}

function buildMenu() {
  const isMac = process.platform === 'darwin';
  // Undo/redo roles are deliberately absent: a menu accelerator on Ctrl/Cmd+Z would
  // take the key before the page's own undo/redo handler.
  const template = [
    ...(isMac ? [{ role: 'appMenu' }] : []),
    { label: 'File', submenu: [isMac ? { role: 'close' } : { role: 'quit' }] },
    {
      label: 'Edit',
      submenu: [{ role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { role: 'togglefullscreen' },
        ...(app.isPackaged ? [] : [{ role: 'toggleDevTools' }]),
      ],
    },
    { role: 'windowMenu' },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(() => {
  // Backs up the page's CSP: nothing leaves or enters over the network.
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
    let allowed = false;
    try {
      allowed = ALLOWED_SCHEMES.includes(new URL(details.url).protocol);
    } catch (_) { /* unparsable URL: cancel */ }
    callback({ cancel: !allowed });
  });
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) =>
    callback(ALLOWED_PERMISSIONS.has(permission)));
  session.defaultSession.setPermissionCheckHandler((_wc, permission) =>
    ALLOWED_PERMISSIONS.has(permission));

  buildMenu();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
