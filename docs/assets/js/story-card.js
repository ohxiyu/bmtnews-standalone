const CARD_WIDTH = 1080;
const CARD_MAX_HEIGHT = 8192;
const SANS_FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif';
const MONO_FONT = 'ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace';

const COLORS = {
  background: '#faf9f7',
  surface: '#f3f2ee',
  border: '#d8d5ce',
  text: '#1b1b18',
  soft: '#4e4c47',
  muted: '#77746e',
  accent: '#1d4c96'
};

const LABELS = {
  zh: {
    title: '分享卡片',
    close: '关闭',
    generating: '正在生成完整长卡…',
    download: '下载 PNG',
    systemShare: '系统分享',
    ready: '完整长卡已生成',
    failed: '卡片生成失败，请重试',
    shareFailed: '系统分享失败，请下载图片后分享'
  },
  en: {
    title: 'Share card',
    close: 'Close',
    generating: 'Generating the full story card…',
    download: 'Download PNG',
    systemShare: 'System share',
    ready: 'Full story card ready',
    failed: 'Could not generate the card. Please try again.',
    shareFailed: 'System sharing failed. Please download the image instead.'
  }
};

let cardGeneration = 0;
let activeCardBlob = null;
let activeCardStory = null;

function cardFilename(story) {
  const rank = String(story.rank || '').replace(/\D+/g, '') || 'story';
  return `bmtnews-${story.date || 'daily'}-${rank}.png`;
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
    download.className = 'share-card-primary';
    download.dataset.cardAction = 'download';
    download.disabled = true;
    const systemShare = document.createElement('button');
    systemShare.type = 'button';
    systemShare.dataset.cardAction = 'system-share';
    systemShare.hidden = true;
    actions.appendChild(download);
    actions.appendChild(systemShare);

    panel.appendChild(header);
    panel.appendChild(preview);
    panel.appendChild(status);
    panel.appendChild(actions);
    dialog.appendChild(panel);
    document.body.appendChild(dialog);

    dialog.addEventListener('click', (event) => {
      if (event.target === dialog || event.target.closest('[data-card-action="close"]')) {
        closeCardDialog(dialog);
      }
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
    systemShare.addEventListener('click', async () => {
      if (!activeCardBlob || !activeCardStory) return;
      const labels = LABELS[activeCardStory.language];
      const file = new File([activeCardBlob], cardFilename(activeCardStory), {type: 'image/png'});
      try {
        await navigator.share({files: [file], title: activeCardStory.title, text: activeCardStory.url});
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
  dialog.querySelector('[data-card-action="system-share"]').textContent = labels.systemShare;
  return dialog;
}

function setFont(context, size, weight, mono) {
  context.font = `${weight} ${size}px ${mono ? MONO_FONT : SANS_FONT}`;
}

function normalizeText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function segmentText(text, language) {
  if (typeof Intl !== 'undefined' && Intl.Segmenter) {
    const segmenter = new Intl.Segmenter(language === 'zh' ? 'zh-CN' : 'en', {
      granularity: 'word'
    });
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
    } else {
      current = next;
    }
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
  lines.forEach((line, index) => {
    context.fillText(line, x, y + index * lineHeight);
  });
  return y + lines.length * lineHeight;
}

function buildLayout(context, story) {
  const contentWidth = CARD_WIDTH - 168;
  setFont(context, 52, 720, false);
  const titleLines = wrapText(context, story.title, contentWidth, story.language);

  setFont(context, 29, 450, false);
  const summaryLines = wrapText(context, story.summary, contentWidth - 66, story.language);

  const sections = story.sections.map((section) => {
    setFont(context, 28, 450, false);
    return {
      title: section.title,
      lines: wrapText(context, section.text, contentWidth, story.language)
    };
  });

  setFont(context, 22, 450, false);
  const sourceLines = wrapText(context, story.source, contentWidth, story.language);
  const linkLines = wrapText(context, story.url, contentWidth, 'en');

  let height = 78 + 42 + 36 + 38 + 1 + 46;
  height += titleLines.length * 70 + 38;
  height += 32 + 30 + 18 + summaryLines.length * 47 + 32;
  sections.forEach((section) => {
    height += 52 + 34 + 16 + section.lines.length * 45;
  });
  if (story.tags) height += 48 + 28 + 44;
  height += 54 + 1 + 42;
  height += sourceLines.length * 35 + 24;
  height += linkLines.length * 35 + 70;

  return {
    height: Math.ceil(height),
    titleLines,
    summaryLines,
    sections,
    sourceLines,
    linkLines
  };
}

function drawCard(context, story, layout) {
  const margin = 84;
  const contentWidth = CARD_WIDTH - margin * 2;
  context.fillStyle = COLORS.background;
  context.fillRect(0, 0, CARD_WIDTH, layout.height);
  context.textBaseline = 'top';

  let y = 72;
  setFont(context, 30, 760, true);
  context.fillStyle = COLORS.text;
  context.fillText('BMTNEWS', margin, y);
  setFont(context, 22, 500, true);
  context.fillStyle = COLORS.muted;
  context.textAlign = 'right';
  context.fillText('bmt.news', CARD_WIDTH - margin, y + 5);
  context.textAlign = 'left';

  y += 78;
  setFont(context, 22, 600, true);
  context.fillStyle = COLORS.accent;
  const meta = [story.date, story.category, story.rank, story.score].filter(Boolean).join('  ·  ');
  context.fillText(meta, margin, y);
  y += 54;
  context.fillStyle = COLORS.border;
  context.fillRect(margin, y, contentWidth, 1);

  y += 46;
  setFont(context, 52, 720, false);
  context.fillStyle = COLORS.text;
  y = drawLines(context, layout.titleLines, margin, y, 70) + 38;

  const summaryHeight = 32 + 30 + 18 + layout.summaryLines.length * 47 + 32;
  context.fillStyle = COLORS.surface;
  context.fillRect(margin, y, contentWidth, summaryHeight);
  context.fillStyle = COLORS.accent;
  context.fillRect(margin, y, 6, summaryHeight);
  setFont(context, 22, 700, true);
  context.fillText(story.language === 'zh' ? '事件摘要' : 'EVENT SUMMARY', margin + 34, y + 30);
  setFont(context, 29, 450, false);
  context.fillStyle = COLORS.soft;
  drawLines(context, layout.summaryLines, margin + 34, y + 78, 47);
  y += summaryHeight;

  layout.sections.forEach((section) => {
    y += 52;
    setFont(context, 24, 720, true);
    context.fillStyle = COLORS.accent;
    context.fillText(section.title, margin, y);
    y += 50;
    setFont(context, 28, 450, false);
    context.fillStyle = COLORS.soft;
    y = drawLines(context, section.lines, margin, y, 45);
  });

  if (story.tags) {
    y += 48;
    setFont(context, 23, 600, true);
    context.fillStyle = COLORS.accent;
    context.fillText(story.tags, margin, y);
    y += 44;
  }

  y += 54;
  context.fillStyle = COLORS.border;
  context.fillRect(margin, y, contentWidth, 1);
  y += 42;

  setFont(context, 22, 450, false);
  context.fillStyle = COLORS.muted;
  y = drawLines(context, layout.sourceLines, margin, y, 35) + 24;
  setFont(context, 22, 600, true);
  context.fillStyle = COLORS.accent;
  drawLines(context, layout.linkLines, margin, y, 35);
}

export async function renderStoryCard(story) {
  if (document.fonts && document.fonts.ready) {
    await document.fonts.ready;
  }
  const measuringCanvas = document.createElement('canvas');
  const measuringContext = measuringCanvas.getContext('2d');
  if (!measuringContext) throw new Error('Canvas is not supported');
  const layout = buildLayout(measuringContext, story);
  if (layout.height > CARD_MAX_HEIGHT) {
    throw new Error(story.language === 'zh' ? '内容过长，无法生成单张卡片' : 'This story is too long for one card');
  }

  const canvas = document.createElement('canvas');
  canvas.width = CARD_WIDTH;
  canvas.height = layout.height;
  canvas.setAttribute('aria-label', story.language === 'zh' ? '分享卡片预览' : 'Share card preview');
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas is not supported');
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
  const systemShare = dialog.querySelector('[data-card-action="system-share"]');
  const generation = ++cardGeneration;
  activeCardBlob = null;
  activeCardStory = null;
  preview.replaceChildren();
  preview.classList.add('is-loading');
  status.textContent = labels.generating;
  download.disabled = true;
  systemShare.hidden = true;

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
    if (navigator.canShare && typeof File === 'function') {
      const file = new File([blob], cardFilename(story), {type: 'image/png'});
      systemShare.hidden = !navigator.canShare({files: [file]});
    }
  } catch (error) {
    if (generation !== cardGeneration) return;
    preview.classList.remove('is-loading');
    status.textContent = error && error.message ? error.message : labels.failed;
  }
}
