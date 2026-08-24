import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import type * as React from "react"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex min-h-10 shrink-0 cursor-default items-center justify-center gap-2 rounded-lg border border-transparent px-3 text-sm font-semibold whitespace-nowrap outline-none transition-[background-color,border-color,color,box-shadow,transform] duration-150 disabled:pointer-events-none disabled:opacity-45 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/35 active:translate-y-px [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[0_1px_0_rgb(255_255_255_/_0.08)_inset] hover:bg-primary/90",
        secondary:
          "border-border bg-secondary text-secondary-foreground hover:bg-accent hover:text-accent-foreground",
        outline:
          "border-border bg-transparent text-foreground hover:border-border-strong hover:bg-accent",
        ghost: "text-muted-foreground hover:bg-accent hover:text-foreground",
        success:
          "border-success/30 bg-success/12 text-success hover:bg-success/18",
        destructive:
          "bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive/35",
      },
      size: {
        default: "h-10",
        sm: "h-9 min-h-9 rounded-md px-2.5 text-xs",
        lg: "h-11 min-h-11 px-4",
        icon: "size-10 min-h-10 px-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
)

function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<typeof ButtonPrimitive> &
  VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button }
