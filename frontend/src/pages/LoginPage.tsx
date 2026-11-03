import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { ErrorBanner } from '../components/ErrorState';
import { Spinner } from '../components/Spinner';
import { ApiError } from '../services/api/http';

/* Small inline glyphs used only on this page (24x24, stroke = currentColor). */
const G = ({ children, size = 20 }: { children: ReactNode; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
);
const IconShield = () => <G><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></G>;
const IconBolt = () => <G><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z" /></G>;
const IconTeam = () => <G><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8" /><path d="M18.5 14.2A6.5 6.5 0 0 1 21.5 20" /></G>;
const IconChart = () => <G><path d="M5 20V12" /><path d="M10.5 20V8" /><path d="M16 20v-6" /><path d="M21 20V5" /></G>;
const IconUser = () => <G size={18}><circle cx="12" cy="8" r="4" /><path d="M20 21a8 8 0 0 0-16 0" /></G>;
const IconLock = () => <G size={18}><rect x="4.5" y="10.5" width="15" height="10.5" rx="2.2" /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" /><path d="M12 15v2.2" /></G>;
const IconEye = () => <G size={18}><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></G>;
const IconEyeOff = () => <G size={18}><path d="M3 3l18 18" /><path d="M10.6 5.1A10.8 10.8 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1" /><path d="M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /></G>;
const IconSignIn = () => <G size={18}><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><path d="M10 17l5-5-5-5" /><path d="M15 12H3" /></G>;

const FEATURES = [
  { icon: <IconShield />, title: 'Secure Access', text: 'Signed licences, hardware binding and maker-checker approval.', tone: 'bg-[linear-gradient(140deg,#60a5fa,#6366f1)]' },
  { icon: <IconBolt />, title: 'Faster Approvals', text: 'Requests from the apps land in the portal and activate on approval.', tone: 'bg-[linear-gradient(140deg,#818cf8,#8b5cf6)]' },
  { icon: <IconTeam />, title: 'Better Collaboration', text: 'Makers, checkers and admins work from one shared queue.', tone: 'bg-[linear-gradient(140deg,#a78bfa,#c084fc)]' },
  { icon: <IconChart />, title: 'Full Visibility', text: 'Licence status, activations, renewals and audit history.', tone: 'bg-[linear-gradient(140deg,#38bdf8,#3b82f6)]' },
];

/* Shared pieces of the sign-in design. Colours come from the --lg-* variables
   that `.lg` (styles/parts/login.css) defines for the light and dark theme. */
const BLOB = 'pointer-events-none absolute rounded-[50%] opacity-[0.55] [filter:blur(70px)] dark:opacity-[0.18]';
const BRAND = 'flex items-center gap-4';
const LOGO =
  'flex h-16 w-16 flex-none items-center justify-center rounded-[16px] bg-[image:var(--lg-logo)] text-[30px] font-extrabold tracking-[-0.04em] text-[#0b1530] ' +
  'shadow-[0_12px_28px_rgba(99,102,241,0.28),inset_0_1px_0_rgba(255,255,255,0.55)] max-[560px]:h-[52px] max-[560px]:w-[52px] max-[560px]:rounded-[14px] max-[560px]:text-[24px]';
const BRAND_NAME = 'm-0 text-[22px] font-bold tracking-[-0.02em] text-[var(--lg-ink)]';
const BRAND_TAG = 'mt-[3px] text-md text-[var(--lg-ink-2)]';
const LABEL = 'mx-0 mb-[9px] mt-0 block text-md font-semibold text-[var(--lg-ink)]';
const REQ = 'text-[#ef4444]';
const FIELD =
  'relative mb-[22px] flex h-[52px] items-center rounded-[12px] border border-solid border-[var(--lg-field-border)] bg-[var(--lg-field)] [transition:border-color_0.15s,box-shadow_0.15s] ' +
  'focus-within:border-[var(--lg-focus)] focus-within:shadow-[0_0_0_4px_rgba(59,130,246,0.14)]';
const FIELD_ICON = 'flex py-0 pl-[18px] pr-3 text-[var(--lg-ink-2)]';
/* font:inherit resets the size, hence the important size; shadow-none keeps the global focus ring out of the field. */
const FIELD_INPUT =
  'h-full min-w-0 flex-1 border-0 bg-transparent pr-4 text-[var(--lg-ink)] shadow-none outline-0 [font:inherit] !text-[15px] placeholder:text-[var(--lg-ink-3)] ' +
  '[&:-webkit-autofill]:[-webkit-box-shadow:0_0_0_40px_transparent_inset] [&:-webkit-autofill]:[transition:background-color_9999s]';

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      const next = searchParams.get('next');
      navigate(next && next.startsWith('/') ? decodeURIComponent(next) : '/', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Login failed'));
      setBusy(false);
    }
  };

  return (
    <div className="lg relative flex min-h-screen items-center justify-center overflow-hidden bg-[image:var(--lg-bg)] px-6 py-10 text-[var(--lg-ink)] max-[560px]:px-4 max-[560px]:py-5">
      <div className={`${BLOB} -left-[120px] top-[30%] h-[420px] w-[420px] bg-[#bfe6ff]`} aria-hidden="true" />
      <div className={`${BLOB} -right-[100px] -top-20 h-[380px] w-[380px] bg-[#e3ccff]`} aria-hidden="true" />
      <div className={`${BLOB} -bottom-40 right-[15%] h-[300px] w-[460px] bg-[#ffd6ea]`} aria-hidden="true" />

      <div className="relative z-[1] grid w-full max-w-[1180px] grid-cols-[1.05fr_1fr] items-center gap-16 max-[980px]:max-w-[560px] max-[980px]:grid-cols-[1fr] max-[980px]:gap-9">
        {/* ---------- left: brand + value ---------- */}
        <section className="pl-6 pr-2 max-[980px]:p-0 max-[560px]:hidden">
          <div className={BRAND}>
            <div className={LOGO}>K</div>
            <div>
              <div className={BRAND_NAME}>K License Center</div>
              <div className={BRAND_TAG}>Manage licenses. Simplify operations.</div>
            </div>
          </div>

          <h1 className="mx-0 mb-0 mt-11 text-[length:clamp(34px,4.2vw,50px)] font-extrabold leading-[1.15] tracking-[-0.03em] text-[var(--lg-ink)] max-[980px]:mt-[26px]">
            Your License
            <br />
            Management <span className="bg-[image:var(--lg-grad)] bg-clip-text text-transparent">Hub</span>
          </h1>
          <p className="mx-0 mb-0 mt-5 text-[17px] leading-[1.6] text-[var(--lg-ink-2)] max-[980px]:[&_br]:hidden">
            Track, manage and approve licenses —
            <br />
            all in one place. Fast, secure and simple.
          </p>

          <ul className="mx-0 mb-0 mt-[34px] grid list-none gap-6 p-0 max-[980px]:hidden">
            {FEATURES.map((f, i) => (
              <li key={f.title} className="flex items-center gap-5">
                <span
                  className={`flex h-[60px] w-[60px] flex-none items-center justify-center rounded-[50%] text-white shadow-[0_10px_24px_rgba(99,102,241,0.25),inset_0_1px_0_rgba(255,255,255,0.35)] [&_svg]:h-[26px] [&_svg]:w-[26px] ${f.tone}`}
                >
                  {f.icon}
                </span>
                <span>
                  <span
                    className={`block text-[17px] font-semibold ${
                      i === 0 ? 'text-[#2563eb] dark:text-[#60a5fa]' : 'text-[var(--lg-ink)]'
                    }`}
                  >
                    {f.title}
                  </span>
                  <span className="mt-1 block max-w-[300px] text-[14.5px] leading-normal text-[var(--lg-ink-2)]">{f.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        {/* ---------- right: sign-in card ---------- */}
        <section
          className="w-full max-w-[560px] justify-self-end rounded-[28px] border border-solid border-[var(--lg-card-border)] bg-[var(--lg-card)] px-10 pb-[30px] pt-10 shadow-[0_30px_70px_rgba(80,90,160,0.16),0_2px_6px_rgba(80,90,160,0.06)] [backdrop-filter:blur(22px)_saturate(140%)] max-[980px]:justify-self-stretch max-[560px]:rounded-[22px] max-[560px]:px-[22px] max-[560px]:pb-[22px] max-[560px]:pt-7"
          aria-labelledby="lg-heading"
        >
          <div className={`${BRAND} mb-[30px]`}>
            <div className={LOGO}>K</div>
            <div>
              <h2 id="lg-heading" className={BRAND_NAME}>K License Center</h2>
              <div className={BRAND_TAG}>Sign in to manage licenses</div>
            </div>
          </div>

          <ErrorBanner error={error} />

          <form onSubmit={handleSubmit} noValidate>
            <label className={LABEL} htmlFor="login-username">
              Username <span className={REQ}>*</span>
            </label>
            <div className={FIELD}>
              <span className={FIELD_ICON}><IconUser /></span>
              <input
                id="login-username"
                className={FIELD_INPUT}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your username"
                autoComplete="username"
                autoFocus
              />
            </div>

            <label className={LABEL} htmlFor="login-password">
              Password <span className={REQ}>*</span>
            </label>
            <div className={FIELD}>
              <span className={FIELD_ICON}><IconLock /></span>
              <input
                id="login-password"
                className={FIELD_INPUT}
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                autoComplete="current-password"
              />
              <button
                type="button"
                className="mr-1 flex h-11 w-11 cursor-pointer items-center justify-center rounded-[10px] border-0 bg-transparent text-[var(--lg-ink-2)] hover:bg-[rgba(99,102,241,0.08)] hover:text-[var(--lg-ink)]"
                onClick={() => setShowPw((v) => !v)}
                aria-label={showPw ? 'Hide password' : 'Show password'}
                title={showPw ? 'Hide password' : 'Show password'}
              >
                {showPw ? <IconEyeOff /> : <IconEye />}
              </button>
            </div>

            {/* lg-submit: no styles, kept as the hook the verification/portal-e2e scripts click */}
            <button
              type="submit"
              className="lg-submit mt-1 flex h-[54px] w-full cursor-pointer items-center justify-center gap-2.5 rounded-[12px] border-0 bg-[linear-gradient(90deg,#38bdf8_0%,#3b82f6_45%,#8b5cf6_80%,#a855f7_100%)] text-white shadow-[0_12px_26px_rgba(79,70,229,0.28)] [font:inherit] !text-[17px] !font-semibold [transition:transform_0.12s,box-shadow_0.12s,filter_0.12s] enabled:hover:shadow-[0_16px_32px_rgba(79,70,229,0.34)] enabled:hover:[filter:brightness(1.04)] enabled:hover:[transform:translateY(-1px)] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={busy || !username.trim() || !password}
            >
              {busy ? <Spinner size={16} /> : <IconSignIn />}
              <span>{busy ? 'Signing in…' : 'Sign in'}</span>
            </button>
          </form>

          <div className="mt-[30px] pt-[22px] text-center text-[14.5px] text-[var(--lg-ink-2)] [border-top:1px_solid_var(--lg-field-border)] [&_a:hover]:underline [&_a]:font-semibold [&_a]:text-[#2563eb] [&_a]:no-underline dark:[&_a]:text-[#60a5fa]">
            Need a licence? <Link to="/request">Request one</Link>
          </div>
          <div className="mt-3 text-center text-xs uppercase tracking-[0.12em] text-[var(--lg-ink-3)]">K License Center · Authorization Console</div>
        </section>
      </div>
    </div>
  );
}
