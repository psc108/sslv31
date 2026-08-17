import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
})

// Attach auth from localStorage
api.interceptors.request.use((config) => {
  // Prefer JWT token if available
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`
  } else {
    // Fall back to legacy API key
    const apiKey = localStorage.getItem('api_key')
    if (apiKey) {
      config.headers['X-API-Key'] = apiKey
    }
  }
  // Tenant header
  const tenant = localStorage.getItem('active_tenant')
  if (tenant && tenant !== 'default') {
    config.headers['X-Tenant'] = tenant
  }
  // Only set Content-Type for non-FormData requests
  if (!(config.data instanceof FormData)) {
    config.headers['Content-Type'] = 'application/json'
  }
  return config
})

// Handle 401 responses — redirect to login
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config.url?.includes('/auth/login')) {
      // Don't redirect if we're already on login
      if (!window.location.pathname.includes('/login')) {
        localStorage.removeItem('auth_token')
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default api
