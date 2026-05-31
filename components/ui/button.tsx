import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-[70px] border border-transparent bg-clip-padding text-sm font-medium whitespace-nowrap transition-all outline-none select-none focus-visible:border-ring focus-visible:ring-1 focus-visible:ring-ring/50 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-1 aria-invalid:ring-destructive/20 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "bg-hope-blue text-white shadow-[rgba(154,207,246,0.5)_0px_7px_0px_0px] hover:bg-primary-active hover:shadow-[rgba(154,207,246,0.5)_0px_4px_0px_0px] active:shadow-none",
        outline:
          "border-border bg-card text-foreground hover:border-primary/40 hover:bg-blue-soft hover:text-foreground aria-expanded:bg-blue-soft aria-expanded:text-foreground",
        secondary:
          "bg-secondary text-accent-foreground shadow-[rgba(154,207,246,0.5)_0px_5px_0px_0px] hover:bg-powder-blue hover:shadow-[rgba(154,207,246,0.5)_0px_3px_0px_0px]",
        ghost:
          "hover:bg-blue-soft hover:text-foreground aria-expanded:bg-blue-soft aria-expanded:text-foreground",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20",
        link: "text-primary underline-offset-4 hover:underline rounded-none shadow-none",
      },
      size: {
        default: "h-9 gap-1.5 px-6",
        xs: "h-6 gap-1 rounded-[100px] px-3 text-xs [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1 px-4 text-xs [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-11 gap-2 px-8 text-base",
        icon: "size-9 rounded-full",
        "icon-xs": "size-6 rounded-full [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8 rounded-full",
        "icon-lg": "size-10 rounded-full",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
