import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';
import './motion.css';

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);

if ('serviceWorker' in navigator && window.isSecureContext && !import.meta.env.DEV) {
  void navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).catch(()=>{ /* Online use continues if offline installation is unavailable. */ });
}
