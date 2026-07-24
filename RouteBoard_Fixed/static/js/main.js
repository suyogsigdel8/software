// Split-flap style character cycling for the hero clock/board.
document.addEventListener("DOMContentLoaded", () => {
  const flaps = document.querySelectorAll(".flap[data-target]");
  flaps.forEach((flap, i) => {
    const target = flap.dataset.target;
    const chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let ticks = 6 + i * 2;
    const interval = setInterval(() => {
      if (ticks <= 0) {
        flap.textContent = target;
        clearInterval(interval);
        return;
      }
      flap.textContent = chars[Math.floor(Math.random() * chars.length)];
      ticks -= 1;
    }, 60);
  });

  // Simulated live bus position along the route line on the tracking page.
  const busEl = document.getElementById("map-bus");
  if (busEl) {
    let progress = parseFloat(busEl.dataset.progress || "0.35");
    const step = () => {
      progress += (Math.random() - 0.3) * 0.03;
      progress = Math.max(0.03, Math.min(0.97, progress));
      busEl.style.left = `calc(${progress * 100}% - 16px)`;
    };
    step();
    setInterval(step, 2500);
  }
});
