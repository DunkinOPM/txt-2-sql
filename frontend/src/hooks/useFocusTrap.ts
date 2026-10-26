import { useEffect, useRef, RefObject } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

export interface UseFocusTrapOptions {
  isOpen: boolean;
  onClose?: () => void;
  initialFocusSelector?: string;
}

/**
 * Checks if an element is currently visible in the DOM layout.
 * Uses getClientRects() to work reliably across display:none, position:fixed, etc.
 */
function isElementVisible(el: HTMLElement): boolean {
  return (
    el.getClientRects().length > 0 &&
    window.getComputedStyle(el).visibility !== 'hidden' &&
    !el.hasAttribute('disabled')
  );
}

/**
 * Custom hook implementing robust WAI-ARIA Dialog (Modal) keyboard interactions:
 * 1. Initial focus: Moves focus to initialFocusSelector or first visible focusable element.
 * 2. Focus trapping: Traps Tab and Shift+Tab within the modal container.
 * 3. Escape key dismissal: Intercepts Escape and invokes onClose().
 * 4. Focus restoration: Restores focus to the opening element on unmount/close without re-render flicker.
 * 5. Edge case resilience: Handles 0 focusable elements, hidden/disabled elements, and out-of-modal focus.
 */
export function useFocusTrap<T extends HTMLElement = HTMLDivElement>({
  isOpen,
  onClose,
  initialFocusSelector,
}: UseFocusTrapOptions): RefObject<T> {
  const containerRef = useRef<T>(null);
  const previousActiveElementRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Track opening focus and restore on close/unmount
  useEffect(() => {
    if (!isOpen) return;

    // Capture the element that held focus immediately before opening
    previousActiveElementRef.current = document.activeElement as HTMLElement | null;

    const container = containerRef.current;
    if (container) {
      if (container.getAttribute('tabindex') === null) {
        container.setAttribute('tabindex', '-1');
      }

      // Small delay to allow children to mount and paint
      const timer = setTimeout(() => {
        if (!container) return;

        if (initialFocusSelector) {
          const initialEl = container.querySelector<HTMLElement>(initialFocusSelector);
          if (initialEl && isElementVisible(initialEl)) {
            initialEl.focus();
            return;
          }
        }

        const focusable = Array.from(
          container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
        ).filter(isElementVisible);

        if (focusable.length > 0) {
          focusable[0].focus();
        } else {
          // If no focusable elements inside, focus the dialog container itself
          container.focus();
        }
      }, 30);

      return () => clearTimeout(timer);
    }

    return () => {
      // Focus restoration on close or unmount
      if (
        previousActiveElementRef.current &&
        typeof previousActiveElementRef.current.focus === 'function'
      ) {
        previousActiveElementRef.current.focus();
      }
    };
  }, [isOpen, initialFocusSelector]);

  // Keyboard navigation & trap listener
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      const container = containerRef.current;
      if (!container) return;

      // Escape key dismissal
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onCloseRef.current?.();
        return;
      }

      // Tab key focus trapping
      if (e.key === 'Tab') {
        const focusableElements = Array.from(
          container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
        ).filter(isElementVisible);

        // Edge case: No focusable elements
        if (focusableElements.length === 0) {
          e.preventDefault();
          container.focus();
          return;
        }

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];
        const activeEl = document.activeElement;

        // Edge case: Focus somehow landed outside container
        if (!container.contains(activeEl)) {
          e.preventDefault();
          if (e.shiftKey) {
            lastElement.focus();
          } else {
            firstElement.focus();
          }
          return;
        }

        if (e.shiftKey) {
          // Shift + Tab: if on first element or on container, cycle to last element
          if (activeEl === firstElement || activeEl === container) {
            e.preventDefault();
            lastElement.focus();
          }
        } else {
          // Tab: if on last element, cycle to first element
          if (activeEl === lastElement) {
            e.preventDefault();
            firstElement.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  return containerRef;
}
