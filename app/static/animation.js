// GSAP owns entrances and data changes; Motion owns spring interactions.
// Native animations keep the experience working without a CDN connection.
(() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const seen = new Set();
  const values = new Map();
  const visible = element => !element.closest('details:not([open])');

  function native(element, frames, options) {
    return element.animate?.(frames, {duration: 400, easing: 'cubic-bezier(.2,.7,.2,1)', ...options});
  }

  function enter(elements) {
    if (reduced.matches || !elements.length) return;
    elements.forEach(element => element.classList.add('is-entering'));
    const finish = () => elements.forEach(element => element.classList.remove('is-entering'));
    if (window.gsap) {
      window.gsap.fromTo(elements, {y: 14, opacity: 0}, {
        y: 0, opacity: 1, duration: .55, stagger: .055,
        ease: 'power3.out', clearProps: 'transform,opacity', onComplete: finish,
      });
    } else {
      elements.forEach((element, i) => {
        const animation = native(element,
          [{opacity: 0, transform: 'translateY(14px)'}, {opacity: 1, transform: 'translateY(0)'}],
          {duration: 550, delay: i * 55, fill: 'backwards'});
        if (animation) {
          animation.onfinish = () => element.classList.remove('is-entering');
          animation.oncancel = animation.onfinish;
        } else element.classList.remove('is-entering');
      });
    }
  }

  function cards(root) {
    const incoming = [];
    root.querySelectorAll('.progress-card').forEach(card => {
      if (!visible(card)) return;
      const id = card.dataset.cardId;
      const key = `${root.id}:${id}`;
      const isNew = !seen.has(key);
      seen.add(key);
      if (isNew) incoming.push(card);
      const fill = card.querySelector('.progress-track>span');
      const current = Number(card.dataset.current);
      const fraction = current / Number(card.dataset.target);
      const previous = values.get(id);
      values.set(id, {current, fraction});
      if (reduced.matches || (!isNew && previous?.fraction === fraction)) return;
      const from = `${(previous?.fraction || 0) * 100}%`;
      const to = `${fraction * 100}%`;
      fill.dataset.targetWidth = to;
      if (window.gsap) {
        window.gsap.fromTo(fill, {width: from}, {
          width: to, duration: .75, delay: isNew ? .12 : 0, ease: 'power2.out',
        });
        if (previous && previous.current !== current) {
          const counter = {value: previous.current};
          const label = card.querySelector('.current-number');
          window.gsap.to(counter, {value: current, duration: .55, ease: 'power2.out',
            onUpdate: () => { label.textContent = Math.round(counter.value).toLocaleString(); },
          });
        }
      } else native(fill, [{width: from}, {width: to}], {duration: 750});
    });
    enter(incoming);
  }

  function calendar(root) {
    const incoming = [...root.querySelectorAll('.time-card')].filter(card => {
      const key = `calendar:${card.dataset.period}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    enter(incoming);
  }

  function dialog(element) {
    if (reduced.matches) return;
    if (window.Motion) window.Motion.animate(element,
      {opacity: [0, 1], scale: [.975, 1], y: [12, 0]},
      {type: 'spring', stiffness: 340, damping: 30});
    else native(element,
      [{opacity: 0, transform: 'translateY(12px) scale(.975)'}, {opacity: 1, transform: 'translateY(0) scale(1)'}],
      {duration: 300});
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button || button.disabled || reduced.matches) return;
    if (window.Motion) window.Motion.animate(button, {scale: [.95, 1]},
      {type: 'spring', stiffness: 450, damping: 24});
    else native(button, [{transform: 'scale(.95)'}, {transform: 'scale(1)'}], {duration: 230});
  }, true);

  document.querySelectorAll('dialog').forEach(element => {
    // Observe native open state so editor and confirmation dialogs share motion.
    new MutationObserver(records => {
      if (records.some(record => record.attributeName === 'open') && element.open) dialog(element);
    }).observe(element, {attributes: true, attributeFilter: ['open']});
  });
  document.getElementById('archive').addEventListener('toggle', event => {
    if (event.target.open) cards(document.getElementById('archive-cards'));
  });
  reduced.addEventListener('change', () => {
    if (!reduced.matches) return;
    document.querySelectorAll('.progress-card,.time-card,dialog,button,.progress-track>span').forEach(element => {
      window.gsap?.killTweensOf(element);
      element.getAnimations?.().forEach(animation => animation.cancel());
      element.style.removeProperty('transform');
      element.style.removeProperty('opacity');
      element.classList.remove('is-entering');
      if (element.dataset.targetWidth) element.style.width = element.dataset.targetWidth;
    });
  });
  window.ProgressMotion = {cards, calendar};
})();
