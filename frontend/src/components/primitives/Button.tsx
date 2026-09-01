import type { ButtonHTMLAttributes, ReactNode } from "react";
import styles from "./Button.module.css";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** primary = amber fill, outline = bordered, ghost = bordered subtle. */
  variant?: "primary" | "outline" | "ghost";
  children: ReactNode;
}

/** The one button. Variants cover the reference's fill / outline / chip styles. */
export function Button({ variant = "outline", className, children, ...rest }: ButtonProps) {
  return (
    <button
      className={[styles.btn, styles[variant], className].filter(Boolean).join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}
