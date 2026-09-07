const CARD_CSS_WIDTH = 440;
const CARD_SCALE = 3;
const CARD_MAX_HEIGHT = 12288;
const X_COMPOSE_URL = 'https://x.com/compose/post';
const SANS_FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif';
const MONO_FONT = 'ui-monospace, "SF Mono", "Cascadia Mono", "JetBrains Mono", Menlo, Consolas, monospace';

const COLORS = {
  background: '#faf9f7', border: '#e4e2dc', text: '#1b1b18', soft: '#4e4c47',
  muted: '#83807a', accent: '#1d4c96', up: '#0e7a4f', warn: '#a05a12', high: '#b33c3c'
};

const METRICS = {
  left: 14, right: 14, headerHeight: 47, railY: 57, metaY: 81,
  titleY: 114,
  xs: 11.5, small: 12.8, body: 15, title: 17,
  xsLine: 17.25, smallLine: 21.76, bodyLine: 25.5, titleLine: 24.65
};

const LABELS = {
  zh: {
    title: '分享', close: '关闭', generating: '正在生成完整长卡…', download: '保存图片',
    xShare: '复制图片并打开 X', ready: '完整长卡已生成', failed: '卡片生成失败，请重试',
    copyReady: '图片已复制，请在 X 编辑器中粘贴后发布',
    copyFailed: '无法复制图片，请保存后手动上传到 X',
    clipboardUnavailable: '当前浏览器不支持复制图片，请保存后上传到 X', details: '背景、讨论与参考资料',
    references: '参考链接', tags: '标签'
  },
  en: {
    title: 'Share', close: 'Close', generating: 'Generating the full story card…', download: 'Save image',
    xShare: 'Copy image and open X', ready: 'Full story card ready',
    failed: 'Could not generate the card. Please try again.',
    copyReady: 'Image copied. Paste it into the X composer to post.',
    copyFailed: 'Could not copy the image. Save it and upload it to X instead.',
    clipboardUnavailable: 'This browser cannot copy images. Save it and upload it to X instead.',
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

export function supportsImageClipboard() {
  return Boolean(window.isSecureContext && navigator.clipboard &&
    typeof navigator.clipboard.write === 'function' && typeof window.ClipboardItem === 'function');
}

export async function copyImageToClipboard(blob, clipboard, ClipboardItemType) {
  const targetClipboard = clipboard || navigator.clipboard;
  const ItemType = ClipboardItemType || window.ClipboardItem;
  const item = new ItemType({'image/png': blob});
  await targetClipboard.write([item]);
}

function actionIcon(kind) {
  const icon = document.createElement('span');
  icon.className = 'share-card-action-icon';
  icon.setAttribute('aria-hidden', 'true');
  if (kind === 'x') {
    icon.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24h-6.657l-5.214-6.817-5.966 6.817H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231 5.45-6.231Zm-1.161 17.52h1.833L7.084 4.126H5.117L17.083 19.77Z"></path></svg>';
  } else {
    icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0 4-4m-4 4-4-4"></path><path d="M5 18v2h14v-2"></path></svg>';
  }
  return icon;
}

function setActionLabel(button, icon, text) {
  const label = document.createElement('span');
  label.textContent = text;
  button.replaceChildren(actionIcon(icon), label);
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
    xShare.disabled = true;
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
      const copyPromise = copyImageToClipboard(activeCardBlob);
      const composerWindow = window.open('about:blank', '_blank');
      try {
        await copyPromise;
        status.textContent = labels.copyReady;
        if (composerWindow) {
          composerWindow.opener = null;
          composerWindow.location.replace(X_COMPOSE_URL);
        } else {
          window.location.assign(X_COMPOSE_URL);
        }
      } catch (error) {
        if (composerWindow && !composerWindow.closed) composerWindow.close();
        status.textContent = labels.copyFailed;
      }
    });
  }

  const labels = LABELS[language];
  dialog.querySelector('[data-card-label="title"]').textContent = labels.title;
  const closeButton = dialog.querySelector('[data-card-action="close"]');
  closeButton.setAttribute('aria-label', labels.close);
  closeButton.title = labels.close;
  setActionLabel(dialog.querySelector('[data-card-action="download"]'), 'download', labels.download);
  setActionLabel(dialog.querySelector('[data-card-action="x-share"]'), 'x', labels.xShare);
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

export function wrapText(context, value, maxWidth, language) {
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
      if (!line && context.measureText(candidate).width > maxWidth) {
        const pieces = breakLongToken(context, token.trimStart(), maxWidth);
        lines.push(...pieces.slice(0, -1));
        line = pieces[pieces.length - 1] || '';
        return;
      }
      if (!line || context.measureText(candidate).width <= maxWidth) {
        line = candidate;
        return;
      }
      const trimmed = token.trimStart();
      if (line && /^[，。！？；：、）】》”’…]/.test(trimmed)) {
        line = candidate;
        return;
      }
      lines.push(line.trimEnd());
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

export function wrapBalancedText(context, value, maxWidth, language) {
  const greedy = wrapText(context, value, maxWidth, language);
  if (greedy.length < 2) return greedy;

  const score = (lines) => {
    const widths = lines.map((line) => context.measureText(line).width);
    const average = widths.reduce((total, width) => total + width, 0) / widths.length;
    return widths.reduce((total, width) => total + ((width - average) ** 2), 0);
  };

  let best = greedy;
  let bestScore = score(greedy);
  const minimumWidth = maxWidth * 0.6;
  for (let width = maxWidth - 2; width >= minimumWidth; width -= 2) {
    const candidate = wrapText(context, value, width, language);
    if (candidate.length !== greedy.length) continue;
    const candidateScore = score(candidate);
    if (candidateScore < bestScore) {
      best = candidate;
      bestScore = candidateScore;
    }
  }
  return best;
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
  const contentX = METRICS.left;
  const contentWidth = CARD_CSS_WIDTH - METRICS.left - METRICS.right;
  const detailsX = contentX + 14;
  const detailsWidth = contentWidth - 14;

  setFont(context, METRICS.title, 700, false);
  const titleLines = wrapBalancedText(context, story.title, contentWidth, story.language);
  setFont(context, METRICS.body, 400, false);
  const summaryBlocks = (Array.isArray(story.summaryParagraphs) && story.summaryParagraphs.length
    ? story.summaryParagraphs
    : String(story.summary || '').split(/\n\s*\n+/)
  ).map(normalizeText).filter(Boolean);
  const summaryParagraphs = summaryBlocks.map((paragraph) => ({
    lines: wrapText(context, paragraph, contentWidth, story.language),
    y: 0
  }));
  const sourceRows = layoutInlineRows(context, sourceSegments(story), contentWidth);

  const titleY = METRICS.titleY;
  let y = titleY;
  y += titleLines.length * METRICS.titleLine + 6;
  const summaryY = y;
  summaryParagraphs.forEach((paragraph, index) => {
    paragraph.y = y;
    y += paragraph.lines.length * METRICS.bodyLine;
    if (index < summaryParagraphs.length - 1) y += 9;
  });
  y += 8;
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
    height: Math.ceil(Math.max(y + 8, 250)), contentX, contentWidth, detailsX, detailsWidth,
    titleY, titleLines, summaryY, summaryParagraphs, sourceY, sourceRows, hasDetails, detailsTop,
    detailsTitleY, sections, references, referencesTitleY, tagsTitleY, tagsY, tagLines,
    detailsBottom: hasDetails ? y - 8 : detailsTop
  };
}

function drawHeader(context) {
  // Reuse the inline master path, without a network request or raster resampling.
  const mark = document.querySelector('.site-brand .site-brand-mark path');
  const markWidth = mark && typeof Path2D !== 'undefined' ? 30 : 0;
  if (markWidth) {
    context.save();
    context.translate(METRICS.left, 11);
    context.scale(24 / 512, 24 / 512);
    context.fillStyle = COLORS.accent;
    context.fill(new Path2D(mark.getAttribute('d')), 'evenodd');
    context.restore();
  }
  setFont(context, 16, 750, false, 0.6);
  context.fillStyle = COLORS.text;
  context.fillText('BMTNews', METRICS.left + markWidth, 17);
  const brandWidth = context.measureText('BMTNews').width;
  setFont(context, METRICS.small, 450, true, 0.7);
  context.fillStyle = COLORS.muted;
  context.fillText('bmt.news', METRICS.left + markWidth + brandWidth + 12, 20);

  context.fillStyle = COLORS.border;
  context.fillRect(0, METRICS.headerHeight - 1, CARD_CSS_WIDTH, 1);
}

function drawCard(context, story, layout) {
  context.fillStyle = COLORS.background;
  context.fillRect(0, 0, CARD_CSS_WIDTH, layout.height);
  context.textBaseline = 'top';
  drawHeader(context);

  setFont(context, METRICS.title, 750, false, 0.35);
  context.fillStyle = story.priority ? COLORS.text : COLORS.muted;
  context.fillText(story.rank || '', METRICS.left, METRICS.railY);
  const rankWidth = context.measureText(story.rank || '').width;
  setFont(context, METRICS.xs, 450, false, 0.4);
  context.fillStyle = COLORS.muted;
  context.fillText(story.dateLabel || story.date || '', METRICS.left + rankWidth + 9, METRICS.railY + 3);

  let metaX = METRICS.left;
  setFont(context, METRICS.xs, 700, false, 1.15);
  context.fillStyle = categoryColor(story.categoryKey);
  context.fillText(story.category, metaX, METRICS.metaY);
  metaX += context.measureText(story.category).width + 10;
  if (story.priority) {
    setFont(context, METRICS.xs, 700, false, 1.15);
    context.fillStyle = COLORS.high;
    context.fillText(story.priority, metaX, METRICS.metaY);
  }

  setFont(context, METRICS.small, 700, true);
  context.fillStyle = scoreColor(story.scoreTier);
  context.textAlign = 'right';
  context.fillText(story.score, CARD_CSS_WIDTH - METRICS.right, METRICS.metaY + 1);
  context.textAlign = 'left';

  setFont(context, METRICS.title, 700, false);
  context.fillStyle = COLORS.text;
  drawLines(context, layout.titleLines, layout.contentX, layout.titleY, METRICS.titleLine);

  setFont(context, METRICS.body, 400, false);
  context.fillStyle = COLORS.soft;
  layout.summaryParagraphs.forEach((paragraph) => {
    drawLines(context, paragraph.lines, layout.contentX, paragraph.y, METRICS.bodyLine);
  });
  drawInlineRows(context, layout.sourceRows, layout.contentX, layout.sourceY);

  if (!layout.hasDetails) {
    return;
  }
  context.fillStyle = COLORS.border;
  context.fillRect(layout.contentX, layout.detailsTop, 2, layout.detailsBottom - layout.detailsTop);

  setFont(context, METRICS.small, 400, false);
  context.fillStyle = COLORS.accent;
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
  xShare.disabled = true;
  download.classList.add('share-card-primary');
  xShare.classList.remove('share-card-primary');

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
    if (supportsImageClipboard()) {
      xShare.disabled = false;
      xShare.classList.add('share-card-primary');
      download.classList.remove('share-card-primary');
      xShare.removeAttribute('title');
    } else {
      xShare.title = labels.clipboardUnavailable;
      status.textContent += ` · ${labels.clipboardUnavailable}`;
    }
  } catch (error) {
    if (generation !== cardGeneration) return;
    preview.classList.remove('is-loading');
    status.textContent = error && error.message ? error.message : labels.failed;
  }
}
