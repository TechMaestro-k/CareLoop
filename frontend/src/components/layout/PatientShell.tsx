import { Outlet, Link } from "react-router-dom";

export function PatientShell() {
  return (
    <div className="flex min-h-screen w-full justify-center bg-background">
      <div className="flex min-h-screen w-full max-w-[480px] flex-col bg-surface shadow-soft">
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <Link to="/p" className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-ink-DEFAULT">
              <span className="text-sm font-bold text-mint">C</span>
            </div>
            <span className="font-display text-base font-semibold text-ink-DEFAULT">CareLoop</span>
          </Link>
          <div className="text-xs text-ink-40">Secure • Encrypted</div>
        </header>
        <main className="flex-1 px-5 py-5 animate-fade-in">
          <Outlet />
        </main>
        <footer className="border-t border-border px-5 py-3 text-center text-[11px] text-ink-40">
          Powered by CareLoop · Your care team
        </footer>
      </div>
    </div>
  );
}
