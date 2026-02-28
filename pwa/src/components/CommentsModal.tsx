import { useState, useEffect } from "react";
import { Send, Loader2 } from "lucide-react";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Avatar } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { getComments, postComment, type Comment } from "@/api/client";

interface CommentsModalProps {
  open: boolean;
  onClose: () => void;
  marketId: string;
}

export function CommentsModal({ open, onClose, marketId }: CommentsModalProps) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [posting, setPosting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    getComments(marketId)
      .then((res) => setComments(res.comments))
      .finally(() => setLoading(false));
  }, [open, marketId]);

  const handlePost = async () => {
    if (!text.trim() || posting) return;
    setPosting(true);
    try {
      const comment = await postComment(marketId, text.trim());
      setComments((prev) => [comment, ...prev]);
      setText("");
    } catch {
      // silently fail
    } finally {
      setPosting(false);
    }
  };

  const timeAgo = (dateStr: string) => {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
  };

  return (
    <BottomSheet open={open} onClose={onClose} title="Comments">
      <div className="flex flex-col h-[50vh]">
        {/* Comments list */}
        <div className="flex-1 overflow-y-auto space-y-4 pb-4">
          {loading && (
            <div className="flex justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-spredd-green" />
            </div>
          )}

          {!loading && comments.length === 0 && (
            <div className="text-center py-8">
              <p className="text-white/40 text-sm">No comments yet</p>
              <p className="text-white/25 text-xs mt-1">Be the first to comment</p>
            </div>
          )}

          {comments.map((comment) => (
            <div key={comment.id} className="flex gap-3">
              <Avatar src={comment.avatar} name={comment.username} size="sm" />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-white">{comment.username}</span>
                  <span className="text-[10px] text-white/30">{timeAgo(comment.created_at)}</span>
                </div>
                <p className="text-sm text-white/70 mt-0.5">{comment.text}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Input */}
        <div className="flex items-center gap-2 pt-3 border-t border-white/8">
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handlePost()}
            placeholder="Add a comment..."
            className="flex-1 bg-white/6 border-white/10 text-white h-10"
          />
          <button
            onClick={handlePost}
            disabled={!text.trim() || posting}
            className="w-10 h-10 rounded-full bg-spredd-green flex items-center justify-center disabled:opacity-50"
          >
            {posting ? (
              <Loader2 className="w-4 h-4 animate-spin text-black" />
            ) : (
              <Send size={16} className="text-black" />
            )}
          </button>
        </div>
      </div>
    </BottomSheet>
  );
}
