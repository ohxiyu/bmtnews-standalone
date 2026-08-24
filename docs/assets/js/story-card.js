const CARD_CSS_WIDTH = 1005;
const CARD_SCALE = 2;
const CARD_MAX_HEIGHT = 8192;
const SANS_FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif';
const MONO_FONT = 'ui-monospace, "SF Mono", "Cascadia Mono", "JetBrains Mono", Menlo, Consolas, monospace';

const COLORS = {
  background: '#faf9f7', border: '#e4e2dc', text: '#1b1b18', soft: '#4e4c47',
  muted: '#83807a', accent: '#1d4c96', up: '#0e7a4f', warn: '#a05a12', high: '#b33c3c'
};

const METRICS = {
  left: 64, right: 48, railWidth: 62, gap: 14, top: 36,
  xs: 11.5, small: 12.8, body: 15, title: 17,
  xsLine: 17.25, smallLine: 21.76, bodyLine: 25.5, titleLine: 24.65
};

const LABELS = {
  zh: {
    title: '分享卡片', close: '关闭', generating: '正在生成完整长卡…', download: '下载图片',
    xShare: '分享到 X', ready: '完整长卡已生成', failed: '卡片生成失败，请重试',
    shareFailed: '无法分享到 X，请下载图片后分享', details: '背景、讨论与参考资料',
    references: '参考链接', tags: '标签'
  },
  en: {
    title: 'Share card', close: 'Close', generating: 'Generating the full story card…', download: 'Download image',
    xShare: 'Share to X', ready: 'Full story card ready',
    failed: 'Could not generate the card. Please try again.',
    shareFailed: 'Could not share to X. Please download the image instead.',
    details: 'Background, discussion, and references', references: 'References', tags: 'Tags'
  }
};

let cardGeneration = 0;
let activeCardBlob = null;
let activeCardStory = null;

function cardFilename(story) {
  const rank = String(story.rank || '').replace(/\D+/g, '') || 'story';
  return `bmtnews-${story.date || 'daily'}-${rank}.png`;
}

export function imageShareData(file) {
  return {files: [file]};
}

function closeCardDialog(dialog) {
  cardGeneration += 1;
  activeCardBlob = null;
  activeCardStory = null;
  const preview = dialog.querySelector('.share-card-preview');
  if (preview) preview.replaceChildren();
  if (typeof dialog.close === 'function') dialog.close();
  else dialog.removeAttribute('open');
}

function ensureCardDialog(language) {
  let dialog = document.querySelector('.share-card-dialog');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.className = 'share-card-dialog';

    const panel = document.createElement('section');
    panel.className = 'share-card-panel';
    const header = document.createElement('header');
    const title = document.createElement('h2');
    title.dataset.cardLabel = 'title';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'share-card-close';
    close.dataset.cardAction = 'close';
    close.textContent = '×';
    header.appendChild(title);
    header.appendChild(close);

    const preview = document.createElement('div');
    preview.className = 'share-card-preview';
    preview.setAttribute('aria-live', 'polite');
    const status = document.createElement('p');
    status.className = 'share-card-status';
    status.setAttribute('role', 'status');

    const actions = document.createElement('footer');
    actions.className = 'share-card-actions';
    const download = document.createElement('button');
    download.type = 'button';
    download.dataset.cardAction = 'download';
    download.disabled = true;
    const xShare = document.createElement('button');
    xShare.type = 'button';
    xShare.className = 'share-card-primary';
    xShare.dataset.cardAction = 'x-share';
    xShare.hidden = true;
    actions.appendChild(download);
    actions.appendChild(xShare);

    panel.appendChild(header);
    panel.appendChild(preview);
    panel.appendChild(status);
    panel.appendChild(actions);
    dialog.appendChild(panel);
    document.body.appendChild(dialog);

    dialog.addEventListener('click', (event) => {
      if (event.target === dialog || event.target.closest('[data-card-action="close"]')) closeCardDialog(dialog);
    });
    dialog.addEventListener('cancel', () => {
      cardGeneration += 1;
      activeCardBlob = null;
      activeCardStory = null;
      preview.replaceChildren();
    });
    download.addEventListener('click', () => {
      if (!activeCardBlob || !activeCardStory) return;
      const objectUrl = URL.createObjectURL(activeCardBlob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = cardFilename(activeCardStory);
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    });
    xShare.addEventListener('click', async () => {
      if (!activeCardBlob || !activeCardStory) return;
      const labels = LABELS[activeCardStory.language];
      const file = new File([activeCardBlob], cardFilename(activeCardStory), {type: 'image/png'});
      try {
        await navigator.share(imageShareData(file));
      } catch (error) {
        if (error && error.name !== 'AbortError') status.textContent = labels.shareFailed;
      }
    });
  }

  const labels = LABELS[language];
  dialog.querySelector('[data-card-label="title"]').textContent = labels.title;
  const closeButton = dialog.querySelector('[data-card-action="close"]');
  closeButton.setAttribute('aria-label', labels.close);
  closeButton.title = labels.close;
  dialog.querySelector('[data-card-action="download"]').textContent = labels.download;
  dialog.querySelector('[data-card-action="x-share"]').textContent = labels.xShare;
  return dialog;
}

function setFont(context, size, weight, mono, letterSpacing = 0) {
  context.font = `${weight} ${size}px ${mono ? MONO_FONT : SANS_FONT}`;
  if ('letterSpacing' in context) context.letterSpacing = `${letterSpacing}px`;
}

function normalizeText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function segmentText(text, language) {
  if (typeof Intl !== 'undefined' && Intl.Segmenter) {
    const segmenter = new Intl.Segmenter(language === 'zh' ? 'zh-CN' : 'en', {granularity: 'word'});
    return Array.from(segmenter.segment(text), (part) => part.segment);
  }
  return text.split(/(\s+|(?=[\u2e80-\u9fff])|(?<=[\u2e80-\u9fff]))/).filter(Boolean);
}

function breakLongToken(context, token, maxWidth) {
  const pieces = [];
  let current = '';
  Array.from(token).forEach((character) => {
    const next = current + character;
    if (current && context.measureText(next).width > maxWidth) {
      pieces.push(current);
      current = character;
    } else current = next;
  });
  if (current) pieces.push(current);
  return pieces;
}

function wrapText(context, value, maxWidth, language) {
  const paragraphs = String(value || '').split(/\n+/);
  const lines = [];
  paragraphs.forEach((paragraph, paragraphIndex) => {
    const clean = normalizeText(paragraph);
    if (!clean) {
      if (paragraphIndex < paragraphs.length - 1) lines.push('');
      return;
    }
    let line = '';
    segmentText(clean, language).forEach((token) => {
      const candidate = line + token;
      if (!line || context.measureText(candidate).width <= maxWidth) {
        line = candidate;
        return;
      }
      lines.push(line.trimEnd());
      const trimmed = token.trimStart();
      if (context.measureText(trimmed).width <= maxWidth) {
        line = trimmed;
        return;
      }
      const pieces = breakLongToken(context, trimmed, maxWidth);
      lines.push(...pieces.slice(0, -1));
      line = pieces[pieces.length - 1] || '';
    });
    if (line) lines.push(line.trimEnd());
  });
  return lines.length ? lines : [''];
}

function drawLines(context, lines, x, y, lineHeight) {
  lines.forEach((line, index) => context.fillText(line, x, y + index * lineHeight));
  return y + lines.length * lineHeight;
}

function sourceSegments(story) {
  const parts = story.sourceParts || {};
  const result = [];
  const append = (text, color, weight) => {
    if (!normalizeText(text)) return;
    if (result.length) result.push({text: ' · ', color: COLORS.muted, weight: 450});
    result.push({text: normalizeText(text), color: color, weight: weight});
  };
  append(parts.type, COLORS.muted, 450);
  append(parts.outlet, COLORS.soft, 550);
  append(parts.published, COLORS.muted, 450);
  (parts.extras || []).forEach((extra) => append(extra, COLORS.accent, 450));
  append(parts.provenance, parts.confirmed ? COLORS.up : COLORS.muted, parts.confirmed ? 600 : 450);
  if (!result.length && story.source) append(story.source, COLORS.muted, 450);
  return result;
}

function layoutInlineRows(context, segments, maxWidth) {
  const rows = [[]];
  let rowWidth = 0;
  segments.forEach((segment) => {
    setFont(context, METRICS.small, segment.weight, false);
    const width = context.measureText(segment.text).width;
    if (rowWidth && rowWidth + width > maxWidth && segment.text.trim() !== '·') {
      rows.push([]);
      rowWidth = 0;
    }
    if (!rowWidth && segment.text.trim() === '·') return;
    rows[rows.length - 1].push({...segment, width: width});
    rowWidth += width;
  });
  return rows.filter((row) => row.length);
}

function drawInlineRows(context, rows, x, y) {
  rows.forEach((row, rowIndex) => {
    let cursor = x;
    row.forEach((segment) => {
      setFont(context, METRICS.small, segment.weight, false);
      context.fillStyle = segment.color;
      context.fillText(segment.text, cursor, y + rowIndex * METRICS.smallLine);
      cursor += segment.width;
    });
  });
}

function categoryColor(category) {
  if (['crypto', 'exchange', 'protocol'].includes(category)) return COLORS.accent;
  if (category === 'technology') return COLORS.up;
  if (['policy', 'regulation', 'security'].includes(category)) return COLORS.warn;
  return COLORS.muted;
}

function scoreColor(tier) {
  if (tier === 'high') return COLORS.high;
  if (tier === 'good') return COLORS.accent;
  return COLORS.muted;
}

function buildLayout(context, story) {
  const contentX = METRICS.left + METRICS.railWidth + METRICS.gap;
  const contentWidth = CARD_CSS_WIDTH - contentX - METRICS.right;
  const detailsX = contentX + 14;
  const detailsWidth = contentWidth - 14;

  setFont(context, METRICS.title, 700, false);
  const titleLines = wrapText(context, story.title, contentWidth, story.language);
  setFont(context, METRICS.body, 400, false);
  const summaryLines = wrapText(context, story.summary, contentWidth, story.language);
  const sourceRows = layoutInlineRows(context, sourceSegments(story), contentWidth);

  let y = METRICS.top + 22;
  const titleY = y;
  y += titleLines.length * METRICS.titleLine + 6;
  const summaryY = y;
  y += summaryLines.length * METRICS.bodyLine + 8;
  const sourceY = y;
  y += Math.max(1, sourceRows.length) * METRICS.smallLine + 8;

  const hasDetails = story.sections.length || story.references.length || story.tags.length;
  const detailsTop = y;
  let detailsTitleY = 0;
  const sections = [];
  const references = [];
  let referencesTitleY = 0;
  let tagsTitleY = 0;
  let tagsY = 0;
  let tagLines = [];

  if (hasDetails) {
    detailsTitleY = y;
    y += METRICS.smallLine + 8;
    story.sections.forEach((section) => {
      setFont(context, METRICS.small, 400, false);
      const lines = wrapText(context, section.text, detailsWidth, story.language);
      const item = {title: section.title, titleY: y, textY: y + METRICS.xsLine + 4, lines: lines};
      sections.push(item);
      y = item.textY + lines.length * METRICS.smallLine + 10;
    });

    if (story.references.length) {
      referencesTitleY = y;
      y += METRICS.xsLine + 4;
      story.references.forEach((reference) => {
        setFont(context, METRICS.small, 400, false);
        const lines = wrapText(context, reference, detailsWidth - 20, story.language);
        references.push({y: y, lines: lines});
        y += lines.length * METRICS.smallLine + 2;
      });
      y += 8;
    }

    if (story.tags.length) {
      tagsTitleY = y;
      y += METRICS.xsLine + 4;
      setFont(context, METRICS.xs, 450, true);
      tagLines = wrapText(context, story.tags.join('  '), detailsWidth, story.language);
      tagsY = y;
      y += tagLines.length * METRICS.xsLine + 10;
    }
  }

  return {
    height: Math.ceil(Math.max(y + 26, METRICS.top + 70)), contentX, contentWidth, detailsX, detailsWidth,
    titleY, titleLines, summaryY, summaryLines, sourceY, sourceRows, hasDetails, detailsTop,
    detailsTitleY, sections, references, referencesTitleY, tagsTitleY, tagsY, tagLines,
    detailsBottom: hasDetails ? y - 8 : detailsTop
  };
}

function drawCard(context, story, layout) {
  context.fillStyle = COLORS.background;
  context.fillRect(0, 0, CARD_CSS_WIDTH, layout.height);
  context.textBaseline = 'top';

  setFont(context, METRICS.small, 700, true);
  context.fillStyle = COLORS.accent;
  context.fillText('bmt.news', METRICS.left, METRICS.top + 3);
  setFont(context, METRICS.xs, 450, false);
  context.fillStyle = COLORS.muted;
  context.fillText(story.dateLabel || story.date || '', METRICS.left, METRICS.top + 29);

  let metaX = layout.contentX;
  setFont(context, METRICS.xs, 700, false, 1.15);
  context.fillStyle = categoryColor(story.categoryKey);
  context.fillText(story.category, metaX, METRICS.top);
  metaX += context.measureText(story.category).width + 10;
  if (story.priority) {
    setFont(context, METRICS.xs, 700, false, 1.15);
    context.fillStyle = COLORS.high;
    context.fillText(story.priority, metaX, METRICS.top);
  }

  setFont(context, METRICS.small, 700, true);
  context.fillStyle = scoreColor(story.scoreTier);
  context.textAlign = 'right';
  context.fillText(story.score, CARD_CSS_WIDTH - METRICS.right, METRICS.top - 1);
  context.textAlign = 'left';

  setFont(context, METRICS.title, 700, false);
  context.fillStyle = COLORS.text;
  drawLines(context, layout.titleLines, layout.contentX, layout.titleY, METRICS.titleLine);

  setFont(context, METRICS.body, 400, false);
  context.fillStyle = COLORS.soft;
  drawLines(context, layout.summaryLines, layout.contentX, layout.summaryY, METRICS.bodyLine);
  drawInlineRows(context, layout.sourceRows, layout.contentX, layout.sourceY);

  if (!layout.hasDetails) return;
  context.fillStyle = COLORS.border;
  context.fillRect(layout.contentX, layout.detailsTop, 2, layout.detailsBottom - layout.detailsTop);

  setFont(context, METRICS.small, 400, false);
  context.fillStyle = COLORS.muted;
  const detailsTitle = normalizeText(story.detailsTitle) || LABELS[story.language].details;
  context.fillText(`${detailsTitle} −`, layout.detailsX, layout.detailsTitleY);

  layout.sections.forEach((section) => {
    setFont(context, METRICS.xs, 700, false, 1.15);
    context.fillStyle = COLORS.muted;
    context.fillText(section.title, layout.detailsX, section.titleY);
    setFont(context, METRICS.small, 400, false);
    context.fillStyle = COLORS.soft;
    drawLines(context, section.lines, layout.detailsX, section.textY, METRICS.smallLine);
  });

  if (layout.references.length) {
    setFont(context, METRICS.xs, 700, false, 1.15);
    context.fillStyle = COLORS.muted;
    context.fillText(LABELS[story.language].references, layout.detailsX, layout.referencesTitleY);
    layout.references.forEach((reference) => {
      setFont(context, METRICS.small, 400, false);
      context.fillStyle = COLORS.soft;
      context.fillText('•', layout.detailsX + 2, reference.y);
      context.fillStyle = COLORS.accent;
      drawLines(context, reference.lines, layout.detailsX + 18, reference.y, METRICS.smallLine);
    });
  }

  if (layout.tagLines.length) {
    setFont(context, METRICS.xs, 700, false, 1.15);
    context.fillStyle = COLORS.muted;
    context.fillText(LABELS[story.language].tags, layout.detailsX, layout.tagsTitleY);
    setFont(context, METRICS.xs, 450, true);
    context.fillStyle = COLORS.muted;
    drawLines(context, layout.tagLines, layout.detailsX, layout.tagsY, METRICS.xsLine);
  }
}

export async function renderStoryCard(story) {
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  story.sections = Array.isArray(story.sections) ? story.sections : [];
  story.references = Array.isArray(story.references) ? story.references : [];
  story.tags = Array.isArray(story.tags) ? story.tags : [];

  const measuringCanvas = document.createElement('canvas');
  const measuringContext = measuringCanvas.getContext('2d');
  if (!measuringContext) throw new Error('Canvas is not supported');
  const layout = buildLayout(measuringContext, story);
  const rasterHeight = layout.height * CARD_SCALE;
  if (rasterHeight > CARD_MAX_HEIGHT) {
    throw new Error(story.language === 'zh' ? '内容过长，无法生成单张卡片' : 'This story is too long for one card');
  }

  const canvas = document.createElement('canvas');
  canvas.width = CARD_CSS_WIDTH * CARD_SCALE;
  canvas.height = rasterHeight;
  canvas.setAttribute('aria-label', story.language === 'zh' ? '分享卡片预览' : 'Share card preview');
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas is not supported');
  context.scale(CARD_SCALE, CARD_SCALE);
  drawCard(context, story, layout);
  return canvas;
}

export function canvasToBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('PNG export failed'));
    }, 'image/png');
  });
}

export async function openStoryCard(story) {
  const labels = LABELS[story.language];
  const dialog = ensureCardDialog(story.language);
  const preview = dialog.querySelector('.share-card-preview');
  const status = dialog.querySelector('.share-card-status');
  const download = dialog.querySelector('[data-card-action="download"]');
  const xShare = dialog.querySelector('[data-card-action="x-share"]');
  const generation = ++cardGeneration;
  activeCardBlob = null;
  activeCardStory = null;
  preview.replaceChildren();
  preview.classList.add('is-loading');
  status.textContent = labels.generating;
  download.disabled = true;
  download.classList.add('share-card-primary');
  xShare.classList.remove('share-card-primary');
  xShare.hidden = true;

  if (!dialog.open) {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  }

  try {
    const canvas = await renderStoryCard(story);
    const blob = await canvasToBlob(canvas);
    if (generation !== cardGeneration) return;
    preview.classList.remove('is-loading');
    preview.replaceChildren(canvas);
    activeCardBlob = blob;
    activeCardStory = story;
    download.disabled = false;
    status.textContent = `${labels.ready} · ${canvas.width} × ${canvas.height} px`;
    const supportsFileShare = typeof navigator.share === 'function' &&
      typeof navigator.canShare === 'function' && typeof File === 'function';
    if (supportsFileShare) {
      try {
        const file = new File([blob], cardFilename(story), {type: 'image/png'});
        if (navigator.canShare(imageShareData(file))) {
          xShare.hidden = false;
          xShare.classList.add('share-card-primary');
          download.classList.remove('share-card-primary');
        }
      } catch {
        // Download remains the primary fallback when file sharing is unavailable.
      }
    }
  } catch (error) {
    if (generation !== cardGeneration) return;
    preview.classList.remove('is-loading');
    status.textContent = error && error.message ? error.message : labels.failed;
  }
}
