import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function SignupPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!username.trim()) return;
    setLoading(true);
    navigate("/account-creating");
  };

  const isValid = username.trim().length >= 3;

  return (
    <div className="h-[100dvh] flex flex-col bg-spredd-bg">
      {/* Header */}
      <div className="flex items-center px-4 pt-14 pb-4">
        <button onClick={() => navigate(-1)} className="text-white/60 hover:text-white">
          <ArrowLeft size={24} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 px-6 pt-8">
        <h1 className="text-3xl font-bold text-white mb-2">
          Choose a username
        </h1>
        <p className="text-white/50 mb-8">
          This is how others will see you on Spredd
        </p>

        <div className="space-y-2">
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40">@</span>
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value.replace(/[^a-zA-Z0-9_]/g, ""))}
              placeholder="username"
              className="pl-8 bg-white/6 border-white/10 text-white h-14 text-lg"
              maxLength={20}
              autoFocus
            />
          </div>
          <p className="text-white/30 text-xs">
            3-20 characters, letters, numbers, and underscores only
          </p>
        </div>
      </div>

      {/* Bottom */}
      <div className="px-6 pb-10">
        <Button
          size="lg"
          className="w-full"
          disabled={!isValid || loading}
          onClick={handleSubmit}
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
