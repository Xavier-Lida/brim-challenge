import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-[12px] border border-dim-gray/60 bg-arctic-mist px-4 py-2 text-sm text-input-charcoal transition-colors outline-none placeholder:text-muted-foreground hover:border-primary/40 focus-visible:border-hope-blue focus-visible:ring-2 focus-visible:ring-hope-blue/20 file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-muted/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-1 aria-invalid:ring-destructive/20",
        className
      )}
      {...props}
    />
  )
}

export { Input }
