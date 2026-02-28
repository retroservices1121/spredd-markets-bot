import { useState } from "react";
import { Copy, Check, ExternalLink } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";

interface ShareModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  url: string;
}

export function ShareModal({ open, onClose, title, url }: ShareModalProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const shareToTwitter = () => {
    window.open(
      `https://twitter.com/intent/tweet?text=${encodeURIComponent(title)}&url=${encodeURIComponent(url)}`,
      "_blank"
    );
  };

  const shareToTelegram = () => {
    window.open(
      `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(title)}`,
      "_blank"
    );
  };

  const handleNativeShare = async () => {
    if (navigator.share) {
      try {
        await navigator.share({ title, url });
      } catch {
        /* user cancelled */
      }
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Share">
      <div className="space-y-3">
        {/* Share buttons */}
        <div className="grid grid-cols-3 gap-3">
          <button
            onClick={shareToTwitter}
            className="flex flex-col items-center gap-2 py-3 rounded-xl bg-white/6 hover:bg-white/10 transition-colors"
          >
            <span className="text-xl">𝕏</span>
            <span className="text-[10px] text-white/50">Twitter</span>
          </button>
          <button
            onClick={shareToTelegram}
            className="flex flex-col items-center gap-2 py-3 rounded-xl bg-white/6 hover:bg-white/10 transition-colors"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" className="text-blue-400">
              <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
            </svg>
            <span className="text-[10px] text-white/50">Telegram</span>
          </button>
          {"share" in navigator && (
            <button
              onClick={handleNativeShare}
              className="flex flex-col items-center gap-2 py-3 rounded-xl bg-white/6 hover:bg-white/10 transition-colors"
            >
              <ExternalLink size={20} className="text-white/60" />
              <span className="text-[10px] text-white/50">More</span>
            </button>
          )}
        </div>

        {/* Copy link */}
        <Button
          variant="outline"
          className="w-full border-white/10"
          onClick={handleCopy}
        >
          {copied ? (
            <>
              <Check size={16} className="text-spredd-green" />
              Copied!
            </>
          ) : (
            <>
              <Copy size={16} />
              Copy Link
            </>
          )}
        </Button>
      </div>
    </Modal>
  );
}
