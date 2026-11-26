const svgWrap = (paths: string, size = 14) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

export const iconImage = svgWrap(
  '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10.5" r="1.5"/><path d="M21 16l-5.5-5.5L5 19"/>',
);
export const iconVideo = svgWrap(
  '<rect x="2" y="5" width="15" height="14" rx="2"/><path d="M17 9l5-3v12l-5-3"/>',
);
export const iconCube = svgWrap(
  '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>',
);
export const iconUndo = svgWrap(
  '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a5 5 0 0 1 5 5v1"/>',
);
export const iconRedo = svgWrap(
  '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a5 5 0 0 0-5 5v1"/>',
);
export const iconDownload = svgWrap(
  '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
  13,
);