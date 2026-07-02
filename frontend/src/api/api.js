/**
 * api.js
 * All API calls to the AIBridge FastAPI backend.
 * Every function handles auth token automatically.
 */

import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8888'

// ── Axios instance with auth header ─────────────────────────────────────────

const api = axios.create({ baseURL: BASE })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('aibridge_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('aibridge_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

// ── Auth ─────────────────────────────────────────────────────────────────────

export const authAPI = {
  signup: (email, password, full_name) =>
    api.post('/auth/signup', { email, password, full_name }),

  login: async (email, password) => {
    const res = await api.post('/auth/login', { email, password })
    if (res.data.access_token) {
      localStorage.setItem('aibridge_token', res.data.access_token)
    }
    return res
  },

  logout: () => {
    localStorage.removeItem('aibridge_token')
    return api.post('/auth/logout')
  },

  me: () => api.get('/auth/me'),
}

// ── ETL Pipeline ──────────────────────────────────────────────────────────────

export const pipelineAPI = {
  run: (source_description, raw_schema, business_requirements) =>
    api.post('/pipeline/run', {
      source_description,
      raw_schema,
      business_requirements
    }),

  save: (name, artifacts, schedule, source_description, raw_schema, biz) =>
    api.post('/pipeline/save', {
      name, artifacts, schedule,
      source_description,
      raw_schema,
      business_requirements: biz
    }),

  list: () => api.get('/pipeline/list'),

  getRuns: (pipeline_id) => api.get(`/pipeline/runs/${pipeline_id}`),
}

// ── SQL ───────────────────────────────────────────────────────────────────────

export const sqlAPI = {
  run: (sql) => api.post('/sql/run', { sql }),
}

// ── Connectors ────────────────────────────────────────────────────────────────

export const connectorAPI = {
  testPostgres: (config) =>
    api.post('/connector/postgres/test', config),

  getPostgresSchema: (config) =>
    api.post('/connector/postgres/schema', config),

  extractTable: (table_name, config) =>
    api.post(`/connector/postgres/extract/${table_name}`, config),

  uploadFile: (file) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/connector/file/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
}

// ── Scheduler ─────────────────────────────────────────────────────────────────

export const schedulerAPI = {
  add: (pipeline_id, pipeline_name, sql_scripts, schedule) =>
    api.post('/scheduler/add', {
      pipeline_id, pipeline_name, sql_scripts, schedule
    }),

  remove: (pipeline_id) =>
    api.delete(`/scheduler/${pipeline_id}`),

  listJobs: () => api.get('/scheduler/jobs'),

  runNow: (pipeline_id) =>
    api.post(`/scheduler/run-now/${pipeline_id}`),
}

// ── Schema Evolution ──────────────────────────────────────────────────────────

export const schemaAPI = {
  evolve: (table_name, existing_columns, new_column, column_type, user_instruction) =>
    api.post('/schema/evolve', {
      table_name, existing_columns, new_column, column_type, user_instruction
    }),
}

// ── Provider ──────────────────────────────────────────────────────────────────

export const providerAPI = {
  get:  () => api.get('/provider'),
  set:  (provider, api_key = '') =>
    api.post('/provider/set', { provider, api_key }),
}

export default api
