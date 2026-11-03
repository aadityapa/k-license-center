# Legacy (archived, not used)

`vehsim-license-server/` — the first, ASP.NET Core + SQLite licence server that used to live inside
the Vehicle SIM repository (`VehSim-NextGen\server`). It is **superseded by the K License Center**
(this folder's `backend` + `frontend`) and was moved here so the Vehicle SIM repository holds only
Vehicle SIM code. It is not built or run; its project still points at
`..\..\src\Karnex.Vbs.Core`, which only resolves inside the Vehicle SIM repository.
Delete this folder once nobody needs it for reference.
