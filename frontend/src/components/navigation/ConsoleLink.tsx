"use client";

import { Loader } from "@mantine/core";
import Link from "next/link";
import { useLinkStatus } from "next/link";
import { useRouter } from "next/navigation";
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  useTransition,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";

import {
  confirmLeave,
  navigationNeedsConfirm,
} from "@/components/navigation/leaveGuard";
import { setNavigationPending } from "@/components/navigation/navigationPending";

export type ConsoleLinkProps = Omit<
  ComponentPropsWithoutRef<typeof Link>,
  "href" | "onNavigate"
> & {
  href: string;
  children?: ReactNode;
};

function LinkPendingMark({ id }: { id: string }) {
  const { pending } = useLinkStatus();
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    setNavigationPending(id, pending);
    const anchor = ref.current?.closest("a");
    if (anchor) {
      if (pending) anchor.setAttribute("data-pending", "true");
      else anchor.removeAttribute("data-pending");
      anchor.setAttribute("aria-busy", pending ? "true" : "false");
    }
    return () => setNavigationPending(id, false);
  }, [id, pending]);
  return (
    <span ref={ref} hidden={!pending}>
      {pending ? <Loader size={12} /> : null}
    </span>
  );
}

export const ConsoleLink = forwardRef<HTMLAnchorElement, ConsoleLinkProps>(
  function ConsoleLink({ href, children, onClick, ...rest }, ref) {
    const router = useRouter();
    const id = useId();
    const [isPending, startTransition] = useTransition();

    useEffect(() => {
      setNavigationPending(id, isPending);
      return () => setNavigationPending(id, false);
    }, [id, isPending]);

    return (
      <Link
        ref={ref}
        href={href}
        onClick={onClick}
        onNavigate={(event) => {
          if (!navigationNeedsConfirm(href)) return;
          event.preventDefault();
          void confirmLeave().then((allowed) => {
            if (!allowed) return;
            startTransition(() => {
              router.push(href);
            });
          });
        }}
        {...rest}
      >
        {children}
        <LinkPendingMark id={`${id}:status`} />
      </Link>
    );
  },
);
