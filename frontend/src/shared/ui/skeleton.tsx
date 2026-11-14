import { cn } from "@/shared/lib/utils"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  )
}

/** What a page shows while its first answer loads: one block where its cards will be, so nothing jumps. */
function PageSkeleton({ className }: { className?: string }) {
  return <Skeleton className={cn("h-96 rounded-2xl", className)} />
}

export { PageSkeleton, Skeleton }
