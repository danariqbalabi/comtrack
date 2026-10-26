import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import Pwa from './Pwa'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Pwa />
    <App />
  </StrictMode>,
)
