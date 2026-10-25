import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  // One primary button per screen: its main action (docs/ui-standard.md §2).
  variant?: "primary" | "secondary" | "danger";
};

export function Button({ variant = "primary", type = "button", className, ...rest }: ButtonProps) {
  const classes = ["button", `button-${variant}`, className].filter(Boolean).join(" ");
  return <button type={type} className={classes} {...rest} />;
}
