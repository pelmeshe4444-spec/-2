import '@fontsource-variable/inter'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router'
import { ApiError, apiOrigin } from './api'
import { App } from './shell'
import './styles.css'

const client = new QueryClient({ defaultOptions: { queries: { staleTime: 5000, retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 1 } } })
const Router = apiOrigin ? HashRouter : BrowserRouter
if (apiOrigin && !location.hash.startsWith('#/')) history.replaceState(history.state, '', '#/')
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><Router><App /></Router></QueryClientProvider>)
