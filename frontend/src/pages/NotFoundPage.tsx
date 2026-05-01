import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

export default function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center justify-center gap-3 py-16 text-center">
      <h1 className="font-display text-4xl font-bold text-ink-DEFAULT">404</h1>
      <p className="text-sm text-ink-60">
        We couldn't find that page. It may have moved or never existed.
      </p>
      <Button asChild>
        <Link to="/dashboard">Back to dashboard</Link>
      </Button>
    </div>
  );
}
