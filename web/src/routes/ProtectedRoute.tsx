import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../store/auth.js'

export default function ProtectedRoute() {
  const isAuthed = useAuth((s) => !!s.accessToken)
  const loc = useLocation()
  if (!isAuthed) {
    // The root, not /login: there is no login page. A node has one password,
    // set on first load, and App renders that screen ahead of the router
    // whenever there is no session — so anywhere without one will do, and the
    // root is the one place guaranteed to exist.
    return (
      <Navigate
        to="/"
        replace
        state={{ from: loc.pathname, sessionExpired: true }}
      />
    )
  }
  return <Outlet />
}
