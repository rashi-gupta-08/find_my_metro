import { useEffect, useRef } from 'react';

// Content stays visible unless an observer can reveal it. Live text updates do
// not restart animations, and keyboard focus never lands in hidden content.
const targets = '.hero, .section, .network-explorer, .journey-card, .station-card, .community-card, .arrival-card, .explorer-data, footer';
const cards = '.journey-card, .station-card, .community-card, .arrival-card';

export function useScrollMotion() {
  const root = useRef<HTMLElement>(null);

  useEffect(() => {
    const main = root.current;
    if (!main) return;
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const registered = new Set<HTMLElement>();
    let observer: IntersectionObserver | undefined;
    let frame = 0;

    const reveal = (element: HTMLElement) => {
      element.dataset.revealState = 'visible';
      observer?.unobserve(element);
    };
    const configureObserver = () => {
      observer?.disconnect();
      observer = undefined;
      if (!preference.matches && 'IntersectionObserver' in window) {
        observer = new IntersectionObserver(entries => {
          entries.forEach(entry => {
            if (entry.isIntersecting) reveal(entry.target as HTMLElement);
          });
        }, { threshold: 0.06, rootMargin: '0px 0px -20px 0px' });
      }
      registered.forEach(reveal);
    };
    configureObserver();

    const register = (element: HTMLElement) => {
      if (registered.has(element)) return;
      registered.add(element);
      if (!observer || element.dataset.revealState === 'visible') {
        reveal(element);
        return;
      }
      if (element.matches(cards) && element.parentElement) {
        const siblings = Array.from(element.parentElement.children).filter(node => node.matches(cards));
        element.style.setProperty('--reveal-delay', `${Math.min(siblings.indexOf(element), 3) * 55}ms`);
      }
      element.dataset.revealState = 'pending';
      observer.observe(element);
    };
    const scan = (element: HTMLElement) => {
      if (element.matches(targets)) register(element);
      element.querySelectorAll<HTMLElement>(targets).forEach(register);
    };
    scan(main);

    const mutations = new MutationObserver(records => {
      records.forEach(record => {
        record.removedNodes.forEach(node => {
          if (!(node instanceof HTMLElement)) return;
          registered.forEach(element => {
            if (node === element || node.contains(element)) {
              observer?.unobserve(element);
              registered.delete(element);
            }
          });
        });
        record.addedNodes.forEach(node => {
          if (node instanceof HTMLElement) scan(node);
        });
      });
    });
    mutations.observe(main, { childList: true, subtree: true });

    const updateProgress = () => {
      frame = 0;
      const maximum = document.documentElement.scrollHeight - window.innerHeight;
      const progress = maximum > 0 ? Math.min(1, Math.max(0, window.scrollY / maximum)) : 0;
      document.documentElement.style.setProperty('--page-scroll-progress', String(progress));
      document.documentElement.toggleAttribute('data-page-scrolled', window.scrollY > 12);
    };
    const scheduleProgress = () => {
      if (!frame) frame = window.requestAnimationFrame(updateProgress);
    };
    const showFocusedContent = (event: FocusEvent) => {
      if (!(event.target instanceof HTMLElement)) return;
      let element: HTMLElement | null = event.target;
      while (element && main.contains(element)) {
        if (element.dataset.revealState === 'pending') reveal(element);
        element = element.parentElement;
      }
    };
    const resize = 'ResizeObserver' in window ? new ResizeObserver(scheduleProgress) : undefined;
    resize?.observe(main);
    main.addEventListener('focusin', showFocusedContent);
    window.addEventListener('scroll', scheduleProgress, { passive: true });
    window.addEventListener('resize', scheduleProgress, { passive: true });
    preference.addEventListener('change', configureObserver);
    scheduleProgress();

    return () => {
      mutations.disconnect();
      observer?.disconnect();
      resize?.disconnect();
      registered.forEach(reveal);
      if (frame) window.cancelAnimationFrame(frame);
      main.removeEventListener('focusin', showFocusedContent);
      window.removeEventListener('scroll', scheduleProgress);
      window.removeEventListener('resize', scheduleProgress);
      preference.removeEventListener('change', configureObserver);
      document.documentElement.style.removeProperty('--page-scroll-progress');
      document.documentElement.removeAttribute('data-page-scrolled');
    };
  }, []);

  return root;
}
