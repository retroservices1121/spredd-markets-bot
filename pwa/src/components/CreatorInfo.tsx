import { Avatar } from "@/components/ui/avatar";

interface CreatorInfoProps {
  username: string;
  avatar?: string;
  onFollow?: () => void;
  following?: boolean;
}

export function CreatorInfo({ username, avatar, onFollow, following }: CreatorInfoProps) {
  return (
    <div className="flex items-center gap-2">
      <Avatar src={avatar} name={username} size="sm" />
      <span className="text-xs font-medium text-white/80">{username}</span>
      {onFollow && (
        <button
          onClick={onFollow}
          className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full transition-all ${
            following
              ? "bg-white/10 text-white/50"
              : "bg-spredd-green text-black"
          }`}
        >
          {following ? "Following" : "Follow"}
        </button>
      )}
    </div>
  );
}
