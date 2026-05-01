import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ChatPanel } from "@/components/ChatPanel";
import { EmptyState } from "@/components/EmptyState";
import { api } from "@/lib/api";

export default function ChatPage() {
  const [patients, setPatients] = useState<any[]>([]);
  const [picked, setPicked] = useState<any | null>(null);

  useEffect(() => {
    api.listPatients().then((d) => {
      const list = d.patients || [];
      setPatients(list);
      setPicked(list[0] || null);
    });
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-2xl font-bold tracking-tight">Chat simulator</h2>
        <p className="text-sm text-ink-60">
          Pretend to be the patient texting CareLoop on WhatsApp. The agent's reply is the same
          logic that runs in production.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Pick a patient</CardTitle>
        </CardHeader>
        <CardContent>
          {patients.length === 0 ? (
            <EmptyState
              title="No patients yet"
              description="Onboard a patient first to use the chat simulator."
            />
          ) : (
            <div className="flex flex-wrap gap-2">
              {patients.map((p) => (
                <Button
                  key={p.id}
                  variant={picked?.id === p.id ? "default" : "outline"}
                  size="sm"
                  onClick={() => setPicked(p)}
                >
                  {p.name}
                  <span className="ml-1 text-xs opacity-70">· {p.language}</span>
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      {picked && <ChatPanel patientId={picked.id} patientName={picked.name} />}
    </div>
  );
}
