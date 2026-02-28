import { Heart, MessageCircle, Share2, Bookmark } from "lucide-react";
import { cn } from "@/lib/utils";

interface FeedActionBarProps {
  liked: boolean;
  bookmarked: boolean;
  likeCount: number;
  commentCount: number;
  onLike: () => void;
  onComment: () => void;
  onShare: () => void;
  onBookmark: () => void;
}

export function FeedActionBar({
  liked,
  bookmarked,
  likeCount,
  commentCount,
  onLike,
  onComment,
  onShare,
  onBookmark,
}: FeedActionBarProps) {
  return (
    <div className="flex flex-col items-center gap-5">
      {/* Like */}
      <button onClick={onLike} className="flex flex-col items-center gap-1">
        <Heart
          size={26}
          className={cn(
            "transition-colors",
            liked ? "fill-spredd-red text-spredd-red" : "text-white/80"
          )}
        />
        <span className="text-[10px] text-white/60">{likeCount}</span>
      </button>

      {/* Comment */}
      <button onClick={onComment} className="flex flex-col items-center gap-1">
        <MessageCircle size={26} className="text-white/80" />
        <span className="text-[10px] text-white/60">{commentCount}</span>
      </button>

      {/* Share */}
      <button onClick={onShare} className="flex flex-col items-center gap-1">
        <Share2 size={24} className="text-white/80" />
      </button>

      {/* Bookmark */}
      <button onClick={onBookmark} className="flex flex-col items-center gap-1">
        <Bookmark
          size={24}
          className={cn(
            "transition-colors",
            bookmarked ? "fill-spredd-green text-spredd-green" : "text-white/80"
          )}
        />
      </button>
    </div>
  );
}
