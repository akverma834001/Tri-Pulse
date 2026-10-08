/**
 * API client module for Project Pulse.
 * Automatically sends CSRF header X-Pulse-Client: 1, credentials, and handles standard errors.
 */

export class ApiError extends Error {
  constructor(message, code, status, details = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function request(url, options = {}) {
  const defaultHeaders = {
    'X-Pulse-Client': '1',
    'Accept': 'application/json',
  };

  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }

  options.headers = {
    ...defaultHeaders,
    ...options.headers,
  };
  options.credentials = 'same-origin';

  let response;
  try {
    response = await fetch(url, options);
  } catch (err) {
    throw new ApiError('Network connection failed. Please check your network.', 'network_error', 0);
  }

  // Handle 401 Unauthorized
  if (response.status === 401) {
    if (!window.location.pathname.endsWith('login.html')) {
      window.location.href = '/login.html';
    }
  }

  // Parse response
  let data = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  } else if (contentType.includes('text/') || contentType.includes('application/zip')) {
    // Binary or text stream
    if (!response.ok) {
      throw new ApiError(`Request failed with status ${response.status}`, `http_${response.status}`, response.status);
    }
    return response;
  }

  if (!response.ok) {
    const errObj = (data && data.error) ? data.error : {};
    const code = errObj.code || `http_${response.status}`;
    const msg = errObj.message || `Request failed with error ${response.status}`;
    throw new ApiError(msg, code, response.status, errObj);
  }

  return data;
}

export const api = {
  get: (url, options = {}) => request(url, { ...options, method: 'GET' }),
  post: (url, body, options = {}) => request(url, { ...options, method: 'POST', body }),
  patch: (url, body, options = {}) => request(url, { ...options, method: 'PATCH', body }),
  put: (url, body, options = {}) => request(url, { ...options, method: 'PUT', body }),
  delete: (url, body, options = {}) => request(url, { ...options, method: 'DELETE', body }),
};
