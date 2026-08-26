(function () {
  'use strict';

  var mainScriptSource = document.currentScript ? document.currentScript.src : '';
  var storyCardModulePromise = null;

  var CATEGORY_ORDER = [
    'all', 'crypto', 'technology', 'policy',
    'exchange', 'security', 'market', 'regulation', 'protocol'
  ];
  var interfaceLanguage = 'zh';
  var CATEGORY_LABELS = {
    zh: {
      all: '全部',
      crypto: 'Crypto',
      policy: '政策',
      exchange: '交易所',
      security: '安全',
      market: '市场',
      regulation: '监管',
      protocol: '协议',
      technology: 'AI / 科技'
    },
    en: {
      all: 'All',
      crypto: 'Crypto',
      policy: 'Policy',
      exchange: 'Exchanges',
      security: 'Security',
      market: 'Markets',
      regulation: 'Regulation',
      protocol: 'Protocols',
      technology: 'AI & Tech'
    }
  };

  var STORY_SHARE_LABELS = {
    zh: {
      card: '分享',
      cardLabel: '生成并分享图片卡片'
    },
    en: {
      card: 'Share',
      cardLabel: 'Generate and share image card'
    }
  };

  var CATEGORY_PATTERNS = {
    security: [
      'security', 'exploit', 'hack', 'hacker', 'breach', 'stolen', 'theft', 'attack',
      'vulnerability', 'drain', '冻结', '黑客', '攻击', '漏洞', '被盗', '安全事件', '资金损失'
    ],
    exchange: [
      'exchange', 'binance', 'okx', 'bybit', 'coinbase', 'kraken', 'listing', 'delisting',
      'deposit', 'withdrawal', 'maintenance', 'trading suspension', '交易所', '上架', '下架',
      '充币', '提币', '暂停交易', '维护'
    ],
    regulation: [
      'regulation', 'regulatory', 'sec ', 'cftc', 'law', 'bill', 'compliance', 'license',
      '监管', '法案', '合规', '牌照', '禁令', '立法'
    ],
    protocol: [
      'protocol', 'bitcoin', 'ethereum', 'solana', 'arbitrum', 'layer 2', 'layer-2',
      'mainnet', 'testnet', 'upgrade', 'fork', 'defi', 'bridge', 'staking', '协议',
      '比特币', '以太坊', '主网', '升级', '跨链桥', '质押'
    ],
    technology: [
      'artificial intelligence', 'machine learning', 'large language model', 'llm',
      'openai', 'anthropic', 'hugging face', 'agentic', 'diffusion model', 'developer tool',
      'github trending', '人工智能', '大模型', '机器学习', '智能体', '扩散模型',
      '开源权重', '开发工具'
    ]
  };

  function normalizeLanguage(value) {
    return String(value || '').toLowerCase().indexOf('en') === 0 ? 'en' : 'zh';
  }

  function textOf(element) {
    return element ? (element.textContent || '').replace(/\s+/g, ' ').trim() : '';
  }

  function summarySentenceUnits(value, language) {
    var text = String(value || '').replace(/\s+/g, ' ').trim();
    if (!text) return [];
    if (language === 'zh') {
      return (text.match(/.*?(?:[。！？!?]+[”’」』】）]?|$)/g) || [])
        .map(function (part) { return part.trim(); })
        .filter(Boolean);
    }

    var units = [];
    var start = 0;
    var endings = /[.!?]+["”’\)\]]*(?=\s+|$)/g;
    var match;
    while ((match = endings.exec(text)) !== null) {
      var candidate = text.slice(start, endings.lastIndex).trim();
      if (/(?:\b[A-Z]\.){2,}$/.test(candidate) ||
          /\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs)\.$/.test(candidate)) {
        continue;
      }
      if (candidate) units.push(candidate);
      start = endings.lastIndex;
    }
    var tail = text.slice(start).trim();
    if (tail) units.push(tail);
    return units.length ? units : [text];
  }

  function splitSummaryParagraphs(value, language) {
    var sentences = summarySentenceUnits(value, language);
    if (sentences.length < 3) return sentences.length ? [sentences.join(language === 'zh' ? '' : ' ')] : [];

    var target = language === 'zh' ? 130 : 240;
    var leadMinimum = language === 'zh' ? 28 : 70;
    var joiner = language === 'zh' ? '' : ' ';
    var paragraphs = [];
    var remaining = sentences;
    if (sentences[0].length >= leadMinimum) {
      paragraphs.push(sentences[0]);
      remaining = sentences.slice(1);
    }

    var current = [];
    var currentLength = 0;
    remaining.forEach(function (sentence) {
      var projected = currentLength + (current.length ? joiner.length : 0) + sentence.length;
      if (current.length && (projected > target || current.length >= 3)) {
        paragraphs.push(current.join(joiner));
        current = [];
        currentLength = 0;
      }
      current.push(sentence);
      currentLength += (currentLength ? joiner.length : 0) + sentence.length;
    });
    if (current.length) paragraphs.push(current.join(joiner));
    return paragraphs;
  }

  function normalizeStorySummary(article, language) {
    var summary = article.querySelector('.story-summary-body');
    if (summary && summary.querySelector('p')) return summary;
    if (!summary) {
      summary = Array.prototype.find.call(
        article.querySelectorAll('.digest-item-content > p'),
        function (paragraph) {
          return !paragraph.classList.contains('source-line') &&
            !paragraph.classList.contains('tag-line');
        }
      );
    }
    if (!summary) return null;

    var paragraphs = splitSummaryParagraphs(textOf(summary), language);
    var wrapper = document.createElement('div');
    wrapper.className = 'story-summary-body';
    paragraphs.forEach(function (text) {
      var paragraph = document.createElement('p');
      paragraph.textContent = text;
      wrapper.appendChild(paragraph);
    });
    summary.replaceWith(wrapper);
    return wrapper;
  }

  function createStoryShareButton(language) {
    var labels = STORY_SHARE_LABELS[language];
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'story-share-button';
    button.dataset.storyShare = 'card';
    button.setAttribute('aria-label', labels.cardLabel);
    button.title = labels.cardLabel;

    var icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('class', 'story-share-icon');
    icon.setAttribute('aria-hidden', 'true');
    icon.setAttribute('viewBox', '0 0 24 24');
    icon.setAttribute('fill', 'none');
    icon.setAttribute('stroke', 'currentColor');
    icon.setAttribute('stroke-width', '1.8');
    icon.setAttribute('stroke-linecap', 'round');
    icon.setAttribute('stroke-linejoin', 'round');
    icon.innerHTML = '<circle cx="18" cy="5" r="2.5"></circle>' +
      '<circle cx="6" cy="12" r="2.5"></circle>' +
      '<circle cx="18" cy="19" r="2.5"></circle>' +
      '<path d="m8.2 10.8 7.6-4.5M8.2 13.2l7.6 4.5"></path>';
    button.appendChild(icon);
    button.appendChild(document.createTextNode(labels.card));
    return button;
  }

  function ensureStoryActions(article, language) {
    var meta = article.querySelector('.digest-item-meta');
    if (!meta) return;
    var controls = meta.querySelector('.digest-item-controls');
    if (!controls) {
      controls = document.createElement('div');
      controls.className = 'digest-item-controls';
      var directScore = Array.prototype.find.call(meta.children, function (child) {
        return child.classList.contains('score-badge');
      });
      if (directScore) controls.appendChild(directScore);
      meta.appendChild(controls);
    }
    controls
      .querySelectorAll('[data-story-share="x"], [data-story-share="image"]')
      .forEach(function (button) {
        button.remove();
      });
    if (!controls.querySelector('[data-story-share="card"]')) {
      controls.appendChild(createStoryShareButton(language));
    }
  }

  function readStory(article) {
    var language = normalizeLanguage(
      (article.closest('[data-language]') || {}).dataset?.language ||
      document.documentElement.lang
    );
    var summaryElement = normalizeStorySummary(article, language);
    if (!summaryElement) {
      summaryElement = Array.prototype.find.call(
        article.querySelectorAll('.digest-item-content > p'),
        function (paragraph) {
          return !paragraph.classList.contains('source-line') &&
            !paragraph.classList.contains('tag-line');
        }
      );
    }
    var summaryParagraphs = summaryElement
      ? Array.prototype.map.call(
        summaryElement.querySelectorAll('p'),
        textOf
      ).filter(Boolean)
      : [];
    if (!summaryParagraphs.length && summaryElement) {
      summaryParagraphs = [textOf(summaryElement)].filter(Boolean);
    }

    var sections = [];
    var references = [];
    var tags = [];
    article.querySelectorAll('.story-more-content > section').forEach(function (section) {
      var title = textOf(section.querySelector('h3'));
      if (section.classList.contains('tag-line')) {
        tags = Array.prototype.map.call(section.querySelectorAll('code'), textOf).filter(Boolean);
        return;
      }
      var entries = Array.prototype.map.call(section.querySelectorAll('li'), textOf).filter(Boolean);
      if (entries.length) {
        references = entries;
        return;
      }
      var content = textOf(section.querySelector('p'));
      if (title && content) sections.push({title: title, text: content});
    });

    var dateHost = article.closest('.daily-day') || article.closest('[data-date]');
    var dateElement = article.querySelector('.digest-item-rail time');
    var date = dateHost?.dataset?.date || dateElement?.getAttribute('datetime') || '';
    var title = textOf(article.querySelector('h2'));
    var sourceLine = article.querySelector('.source-line');
    var sourceLink = sourceLine && sourceLine.querySelector('.source-link');
    var sourceTime = sourceLine && sourceLine.querySelector('time');
    var provenance = sourceLine && sourceLine.querySelector('.provenance');
    var sourceSegments = textOf(sourceLine).split('·').map(function (part) {
      return part.trim();
    }).filter(Boolean);
    var outlet = textOf(sourceLink) || sourceSegments[1] || '';
    var sourceType = sourceSegments[0] || '';
    var published = textOf(sourceTime);
    var provenanceText = textOf(provenance);
    var reservedSourceParts = [sourceType, outlet, published, provenanceText];
    var sourceExtras = sourceSegments.filter(function (part) {
      return reservedSourceParts.indexOf(part) === -1;
    });
    var details = article.querySelector('.story-more > summary');
    var priority = article.querySelector('.priority-pill, .editorial-pill');
    return {
      language: language,
      title: title,
      summary: summaryParagraphs.join('\n\n'),
      summaryParagraphs: summaryParagraphs,
      sections: sections,
      references: references,
      tags: tags,
      source: textOf(article.querySelector('.source-line')),
      sourceParts: {
        type: sourceType,
        outlet: outlet,
        published: published,
        extras: sourceExtras,
        provenance: provenanceText,
        confirmed: Boolean(provenance && provenance.classList.contains('is-confirmed'))
      },
      category: textOf(article.querySelector('.category-pill')),
      categoryKey: article.dataset.category || '',
      priority: textOf(priority),
      detailsTitle: textOf(details),
      score: textOf(article.querySelector('.score-badge')),
      scoreTier: article.querySelector('.score-badge')?.dataset?.tier || 'mid',
      rank: textOf(article.querySelector('.digest-item-rail strong')),
      date: date,
      dateLabel: textOf(dateElement)
    };
  }

  function storyCardModuleUrl() {
    var source = mainScriptSource;
    if (!source) {
      var script = document.querySelector('script[src*="/assets/js/bmtnews-ui.js"]');
      source = script ? script.src : new URL('/assets/js/bmtnews-ui.js', window.location.href).href;
    }
    var base = new URL(source, window.location.href);
    var moduleUrl = new URL('story-card.js', base);
    moduleUrl.search = base.search;
    return moduleUrl.href;
  }

  function loadStoryCardModule() {
    if (!storyCardModulePromise) {
      storyCardModulePromise = import(storyCardModuleUrl()).catch(function (error) {
        storyCardModulePromise = null;
        throw error;
      });
    }
    return storyCardModulePromise;
  }

  function setupStorySharing() {
    document.addEventListener('click', function (event) {
      var button = event.target.closest('[data-story-share]');
      if (!button || button.dataset.storyShare !== 'card') return;
      var article = button.closest('.digest-item');
      if (!article) return;
      var story = readStory(article);
      loadStoryCardModule().then(function (module) {
        module.openStoryCard(story);
      });
    });
  }

  function inferCategory(element) {
    var probe = element.cloneNode(true);
    probe.querySelectorAll('.source-line, details').forEach(function (node) {
      node.remove();
    });
    var text = textOf(probe).toLowerCase();
    var priority = ['security', 'exchange', 'regulation', 'protocol', 'technology'];
    for (var i = 0; i < priority.length; i += 1) {
      var category = priority[i];
      var patterns = CATEGORY_PATTERNS[category];
      for (var j = 0; j < patterns.length; j += 1) {
        if (text.indexOf(patterns[j]) !== -1) return category;
      }
    }
    return 'market';
  }

  function scoreTier(score) {
    if (score >= 9) return 'high';
    if (score >= 7) return 'good';
    if (score >= 5) return 'mid';
    return 'low';
  }

  function readScore(element) {
    if (!element) return 0;
    var badge = element.querySelector('.score-badge');
    if (badge) return parseFloat(textOf(badge)) || 0;
    var match = textOf(element).match(/(\d+(?:\.\d+)?)\s*\/\s*10/);
    return match ? parseFloat(match[1]) : 0;
  }

  function createCategoryPill(category, language) {
    var pill = document.createElement('span');
    pill.className = 'category-pill';
    pill.dataset.category = category;
    pill.textContent = CATEGORY_LABELS[language][category] || CATEGORY_LABELS[language].market;
    return pill;
  }

  function createScoreBadge(score) {
    var badge = document.createElement('span');
    badge.className = 'score-badge';
    badge.dataset.tier = scoreTier(score);
    badge.textContent = score ? score.toFixed(1) : '—';
    badge.setAttribute('aria-label', score ? 'Score ' + score.toFixed(1) + ' out of 10' : 'No score');
    return badge;
  }

  function configureExternalLinks(root) {
    root.querySelectorAll('a[href]').forEach(function (anchor) {
      try {
        var url = new URL(anchor.getAttribute('href'), window.location.href);
        if (
          (url.protocol === 'http:' || url.protocol === 'https:') &&
          url.origin !== window.location.origin
        ) {
          anchor.target = '_blank';
          anchor.rel = 'noopener noreferrer';
        }
      } catch (error) {
        // Invalid links remain inert and are ignored.
      }
    });
  }

  function linkifySourceLine(article) {
    var titleLink = article.querySelector('h2 a[href]');
    var sourceLine = article.querySelector('.source-line');
    if (!titleLink || !sourceLine || sourceLine.querySelector('.source-link')) return;

    var sourceNode = Array.prototype.find.call(sourceLine.childNodes, function (node) {
      return node.nodeType === Node.TEXT_NODE && node.nodeValue.indexOf('·') !== -1;
    });
    if (!sourceNode) return;

    var sourceText = sourceNode.nodeValue;
    var parts = sourceText.split('·');
    if (parts.length < 2 || !parts[1].trim()) return;

    var fragment = document.createDocumentFragment();
    fragment.appendChild(document.createTextNode(parts[0].trim() + ' · '));

    var sourceLink = document.createElement('a');
    sourceLink.className = 'source-link';
    sourceLink.href = titleLink.getAttribute('href');
    sourceLink.textContent = parts[1].trim();
    fragment.appendChild(sourceLink);

    var tail = parts.slice(2).map(function (part) {
      return part.trim();
    }).filter(Boolean).join(' · ');
    if (tail) fragment.appendChild(document.createTextNode(' · ' + tail));
    if (/·\s*$/.test(sourceText)) fragment.appendChild(document.createTextNode(' · '));
    sourceNode.replaceWith(fragment);
  }

  function processScoreBadges(root) {
    var scoreRe = /⭐️?\s*(\d+(?:\.\d+)?)\/10/;
    root.querySelectorAll('h2, h3, li').forEach(function (element) {
      if (element.querySelector('.score-badge')) return;
      var match = element.innerHTML.match(scoreRe);
      if (!match) return;
      var score = parseFloat(match[1]);
      element.innerHTML = element.innerHTML.replace(
        scoreRe,
        '<span class="score-badge" data-tier="' + scoreTier(score) + '">' + score.toFixed(1) + '</span>'
      );
    });
  }

  function markSemanticElements(root) {
    root.querySelectorAll('p').forEach(function (paragraph) {
      var text = textOf(paragraph);
      if (/^(Tags|标签)\s*:/.test(text)) {
        paragraph.classList.add('tag-line');
        return;
      }
      if (/^(rss|reddit|github|hackernews|hn|telegram|google_news|gdelt|ossinsight)\s*·/i.test(text)) {
        paragraph.classList.add('source-line');
      }
    });
  }

  function setupFilters(host, cards, language, onFilter) {
    if (!host || !cards.length) return;

    var counts = {all: cards.length};
    cards.forEach(function (card) {
      var category = card.dataset.category || 'market';
      counts[category] = (counts[category] || 0) + 1;
    });

    var filterBar = document.createElement('div');
    filterBar.className = 'category-filters';

    CATEGORY_ORDER.forEach(function (category) {
      if (category !== 'all' && !counts[category]) return;
      var button = document.createElement('button');
      button.type = 'button';
      button.dataset.category = category;
      if (category === 'all') button.classList.add('active');
      button.setAttribute('aria-pressed', category === 'all' ? 'true' : 'false');
      button.appendChild(document.createTextNode(CATEGORY_LABELS[language][category]));

      var count = document.createElement('span');
      count.textContent = counts[category] || 0;
      button.appendChild(count);
      button.setAttribute(
        'aria-label',
        CATEGORY_LABELS[language][category] + ': ' + (counts[category] || 0)
      );

      button.addEventListener('click', function () {
        filterBar.querySelectorAll('button').forEach(function (candidate) {
          candidate.classList.toggle('active', candidate === button);
          candidate.setAttribute('aria-pressed', candidate === button ? 'true' : 'false');
        });
        cards.forEach(function (card) {
          card.hidden = category !== 'all' && card.dataset.category !== category;
        });
        if (onFilter) onFilter(category);
      });
      filterBar.appendChild(button);
    });

    host.replaceChildren(filterBar);
  }

  function bindStaticFilters(root, cards, tocItems) {
    var filterBar = root.querySelector('[data-static-filters]');
    if (!filterBar || filterBar.dataset.bound === 'true') return;
    filterBar.dataset.bound = 'true';

    filterBar.querySelectorAll('button[data-category]').forEach(function (button) {
      button.addEventListener('click', function () {
        var category = button.dataset.category || 'all';
        filterBar.querySelectorAll('button[data-category]').forEach(function (candidate) {
          candidate.classList.toggle('active', candidate === button);
          candidate.setAttribute('aria-pressed', candidate === button ? 'true' : 'false');
        });
        cards.forEach(function (card) {
          card.hidden = category !== 'all' && card.dataset.category !== category;
        });
        tocItems.forEach(function (item) {
          item.hidden = category !== 'all' && item.dataset.category !== category;
        });
      });
    });
  }

  function isExtraStoryNode(node) {
    if (node.tagName === 'DETAILS' || node.classList.contains('tag-line')) return true;
    if (node.tagName !== 'P') return false;
    var strong = node.querySelector('strong:first-child');
    if (!strong) return false;
    return /^(Background|Discussion|背景|社区讨论)$/.test(textOf(strong));
  }

  function parseFetchedCount(root) {
    var quote = root.querySelector(':scope > blockquote:first-of-type');
    var numbers = quote ? textOf(quote).match(/\d+/g) : null;
    return numbers && numbers.length ? parseInt(numbers[0], 10) : 0;
  }

  function parseRunStat(value) {
    var parsed = parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
  }

  function readRunStats(root) {
    var marker = root.querySelector(':scope > .run-stats');
    if (!marker) {
      return {
        fetched: null,
        analyzed: parseFetchedCount(root)
      };
    }
    return {
      fetched: parseRunStat(marker.dataset.fetched),
      analyzed: parseRunStat(marker.dataset.analyzed)
    };
  }

  function updateFeedStats(scope, articles, root, runStats) {
    var critical = articles.filter(function (article) {
      return parseFloat(article.dataset.score || '0') >= 9;
    }).length;
    var sources = new Set();
    root.querySelectorAll('.source-line').forEach(function (line) {
      var parts = textOf(line).split('·');
      sources.add((parts[1] || parts[0] || '').trim());
    });

    var values = {
      selected: articles.length,
      fetched: runStats.fetched === null ? '—' : runStats.fetched,
      analyzed: runStats.analyzed === null ? '—' : runStats.analyzed,
      critical: critical,
      sources: sources.size || '—'
    };
    Object.keys(values).forEach(function (key) {
      scope.querySelectorAll('[data-stat="' + key + '"]').forEach(function (element) {
        element.textContent = values[key];
      });
    });
  }

  function createStoryMore(article, language) {
    var extras = Array.prototype.slice.call(article.children).filter(isExtraStoryNode);
    if (!extras.length) return;

    var details = document.createElement('details');
    details.className = 'story-more';
    var summary = document.createElement('summary');
    summary.textContent = language === 'zh' ? '背景、讨论与参考资料' : 'Background, discussion, and references';
    var content = document.createElement('div');
    content.className = 'story-more-content';
    extras.forEach(function (extra) {
      content.appendChild(extra);
    });
    details.appendChild(summary);
    details.appendChild(content);
    article.appendChild(details);
  }

  function createDigestArticle(root, heading, index, language, date) {
    var anchorParagraph = heading.previousElementSibling;
    var anchor = anchorParagraph && anchorParagraph.matches('p')
      ? anchorParagraph.querySelector('a[id^="item-"]')
      : null;
    if (!anchor) anchorParagraph = null;

    var article = document.createElement('article');
    article.className = 'digest-item';
    root.insertBefore(article, anchorParagraph || heading);

    var rawId = anchor ? anchor.id : 'item-' + (index + 1);
    var idPrefix = document.body.classList.contains('home-page')
      ? language + '-' + date + '-'
      : '';
    article.id = idPrefix + rawId;
    if (anchorParagraph) anchorParagraph.remove();

    var node = heading;
    while (node && node.tagName !== 'HR') {
      var next = node.nextElementSibling;
      article.appendChild(node);
      node = next;
    }
    if (node && node.tagName === 'HR') node.remove();

    var category = inferCategory(article);
    var score = readScore(heading);
    var headingBadge = heading.querySelector('.score-badge');
    if (headingBadge) headingBadge.remove();
    heading.removeAttribute('id');
    article.dataset.category = category;
    article.dataset.score = String(score);

    var meta = document.createElement('div');
    meta.className = 'digest-item-meta';
    var metaLeft = document.createElement('div');
    metaLeft.appendChild(createCategoryPill(category, language));
    meta.appendChild(metaLeft);
    meta.appendChild(createScoreBadge(score));
    article.insertBefore(meta, heading);

    createStoryMore(article, language);
    linkifySourceLine(article);
    configureExternalLinks(article);

    var content = document.createElement('div');
    content.className = 'digest-item-content';
    while (article.firstChild) {
      content.appendChild(article.firstChild);
    }

    var rail = document.createElement('div');
    rail.className = 'digest-item-rail';
    var number = document.createElement('strong');
    number.textContent = '#' + String(index + 1).padStart(2, '0');
    var shortDate = document.createElement('time');
    shortDate.dateTime = date || '';
    shortDate.textContent = date ? date.slice(5).replace('-', '.') : '';
    rail.appendChild(number);
    rail.appendChild(shortDate);

    article.appendChild(rail);
    article.appendChild(content);
    return article;
  }

  function configureHeadlineDisclosure(details) {
    if (!window.matchMedia) {
      details.open = true;
      return;
    }
    var wide = window.matchMedia('(min-width: 1101px)');
    var sync = function () {
      details.open = wide.matches;
    };
    sync();
    if (wide.addEventListener) wide.addEventListener('change', sync);
    else if (wide.addListener) wide.addListener(sync);
  }

  function configureOverviewDisclosure(details) {
    if (!window.matchMedia) {
      details.open = true;
      return;
    }
    var wide = window.matchMedia('(min-width: 761px)');
    var sync = function () {
      details.open = wide.matches;
    };
    sync();
    if (wide.addEventListener) wide.addEventListener('change', sync);
    else if (wide.addListener) wide.addListener(sync);
  }

  function setupActiveHeadline(articles, tocItems) {
    if (!('IntersectionObserver' in window)) return;
    var byId = {};
    tocItems.forEach(function (item) {
      var link = item.querySelector('a[href^="#"]');
      if (link) byId[link.getAttribute('href').slice(1)] = item;
    });

    var observer = new IntersectionObserver(function (entries) {
      var visible = entries.filter(function (entry) {
        return entry.isIntersecting && !entry.target.hidden;
      }).sort(function (a, b) {
        return a.boundingClientRect.top - b.boundingClientRect.top;
      });
      if (!visible.length) return;
      var active = byId[visible[0].target.id];
      tocItems.forEach(function (item) {
        item.classList.toggle('active', item === active);
      });
      if (active) active.scrollIntoView({block: 'nearest'});
    }, {
      rootMargin: '-16% 0px -70% 0px',
      threshold: 0
    });

    articles.forEach(function (article) {
      observer.observe(article);
    });
  }

  function createHeadlineRail(toc, articles, language, date) {
    var aside = document.createElement('aside');
    aside.className = 'headline-rail';
    aside.setAttribute('aria-label', language === 'zh' ? '当日排行榜' : 'Daily ranking');

    var details = document.createElement('details');
    details.className = 'headline-index';
    var summary = document.createElement('summary');
    var title = document.createElement('span');
    var displayDate = date ? date.replace(/-/g, '.') : '';
    title.textContent = language === 'zh'
      ? displayDate + ' 排行榜'
      : displayDate + ' Ranking';
    var count = document.createElement('small');
    count.textContent = articles.length;
    summary.appendChild(title);
    summary.appendChild(count);
    details.appendChild(summary);

    toc.classList.add('headline-list');
    details.appendChild(toc);
    aside.appendChild(details);
    configureHeadlineDisclosure(details);
    return aside;
  }

  function enhanceDigest(root) {
    if (!root || root.dataset.enhanced === 'true') return;
    root.dataset.enhanced = 'true';
    root.classList.add('daily-feed-content');

    var language = normalizeLanguage(root.dataset.language || document.body.dataset.language || document.documentElement.lang);
    var date = root.dataset.date || document.body.dataset.date || '';
    if (root.querySelector('.feed-rendered-static')) {
      var staticArticles = Array.prototype.slice.call(root.querySelectorAll('.digest-item'));
      var staticTocItems = Array.prototype.slice.call(root.querySelectorAll('.headline-list > li'));
      var staticStream = root.querySelector('.daily-story-stream') || root;
      var staticDetails = root.querySelector('.headline-index');
      var overviewDetails = root.querySelector('.edition-overview-disclosure');
      var staticStats = readRunStats(root);
      var staticStatsScope = root.closest('.daily-day') || root;

      staticArticles.forEach(function (article) {
        normalizeStorySummary(article, language);
        ensureStoryActions(article, language);
      });

      updateFeedStats(
        staticStatsScope,
        staticArticles,
        staticStream,
        staticStats
      );
      bindStaticFilters(root, staticArticles, staticTocItems);
      if (staticDetails) configureHeadlineDisclosure(staticDetails);
      if (overviewDetails) configureOverviewDisclosure(overviewDetails);
      setupActiveHeadline(staticArticles, staticTocItems);
      configureExternalLinks(root);
      return;
    }

    processScoreBadges(root);
    markSemanticElements(root);

    var runStats = readRunStats(root);
    var quote = root.querySelector(':scope > blockquote:first-of-type');
    var selectionText = textOf(quote);
    var toc = root.querySelector(':scope > ol');
    var headings = Array.prototype.slice.call(root.children).filter(function (element) {
      return element.tagName === 'H2';
    });
    if (!toc || !headings.length) return;

    var articles = headings.map(function (heading, index) {
      return createDigestArticle(root, heading, index, language, date);
    });
    articles.forEach(function (article) {
      normalizeStorySummary(article, language);
      ensureStoryActions(article, language);
    });
    var tocItems = Array.prototype.slice.call(toc.querySelectorAll(':scope > li'));
    tocItems.forEach(function (item, index) {
      if (!articles[index]) return;
      item.dataset.category = articles[index].dataset.category;
      var link = item.querySelector('a[href^="#"]');
      if (link) link.setAttribute('href', '#' + articles[index].id);
    });

    var orientation = document.createElement('div');
    orientation.className = 'feed-orientation';
    var note = document.createElement('p');
    note.className = 'feed-selection-note';
    note.textContent = selectionText || (language === 'zh'
      ? '今日重要资讯按影响力排序。'
      : 'Today’s important stories, ranked by impact.');
    var filterHost = document.createElement('div');
    filterHost.className = 'digest-filter-host';
    orientation.appendChild(note);
    orientation.appendChild(filterHost);

    var layout = document.createElement('div');
    layout.className = 'daily-feed-layout is-editorial-grid';
    var stream = document.createElement('div');
    stream.className = 'daily-story-stream';
    articles.forEach(function (article) {
      stream.appendChild(article);
    });
    var aside = createHeadlineRail(toc, articles, language, date);
    layout.appendChild(orientation);
    layout.appendChild(stream);
    layout.appendChild(aside);

    root.replaceChildren(layout);
    var statsScope = root.closest('.daily-day') || root;
    updateFeedStats(statsScope, articles, stream, runStats);
    setupFilters(filterHost, articles, language, function (category) {
      tocItems.forEach(function (item) {
        item.hidden = category !== 'all' && item.dataset.category !== category;
      });
    });
    setupActiveHeadline(articles, tocItems);
  }

  function enhanceHomeSection(section) {
    if (!section) return;
    section.querySelectorAll('.daily-feed-content').forEach(enhanceDigest);
    section.querySelectorAll('.continuous-feed').forEach(setupLoadEarlier);
  }

  function enhanceDailyFeeds() {
    if (document.body.classList.contains('home-page')) {
      enhanceHomeSection(document.body);
    }
    if (document.body.classList.contains('digest-page')) {
      enhanceDigest(document.querySelector('.main-content'));
    }
  }

  function createDayStat(key, label, shortLabel) {
    var stat = document.createElement('span');
    stat.dataset.short = shortLabel;
    var value = document.createElement('strong');
    value.dataset.stat = key;
    value.textContent = '—';
    stat.appendChild(value);
    stat.appendChild(document.createTextNode(' ' + label));
    return stat;
  }

  function createLoadedDay(language, date, source) {
    var section = document.createElement('section');
    section.className = 'daily-day';
    section.dataset.language = language;
    section.dataset.date = date;

    var header = document.createElement('header');
    header.className = 'day-divider';
    var heading = document.createElement('div');
    heading.className = 'day-divider-title';
    var time = document.createElement('time');
    time.dateTime = date;
    time.textContent = date.replace(/-/g, '.');
    heading.appendChild(time);

    var stats = document.createElement('div');
    stats.className = 'day-divider-stats';
    stats.setAttribute('aria-label', date + (language === 'zh' ? ' 日报统计' : ' brief statistics'));
    stats.appendChild(createDayStat('fetched', language === 'zh' ? '条采集' : 'fetched', language === 'zh' ? '采' : 'F'));
    stats.appendChild(createDayStat('analyzed', language === 'zh' ? '条分析' : 'analyzed', language === 'zh' ? '析' : 'A'));
    stats.appendChild(createDayStat('selected', language === 'zh' ? '条展示' : 'displayed', language === 'zh' ? '展' : 'D'));
    stats.appendChild(createDayStat('critical', language === 'zh' ? '条高优先级' : 'high priority', language === 'zh' ? '高' : 'H'));
    header.appendChild(heading);
    header.appendChild(stats);

    var content = document.createElement('div');
    content.className = 'daily-feed-content';
    content.dataset.language = language;
    content.dataset.date = date;
    content.innerHTML = source.innerHTML;

    section.appendChild(header);
    section.appendChild(content);
    return section;
  }

  function setupLoadEarlier(feed) {
    if (!feed || feed.dataset.historyReady === 'true') return;
    feed.dataset.historyReady = 'true';

    var button = feed.querySelector('.load-earlier');
    var manifest = feed.querySelector('.feed-history-manifest');
    var stream = feed.querySelector('.day-stream');
    if (!button || !manifest || !stream) return;

    var language = normalizeLanguage(feed.dataset.language);
    var idleLabel = language === 'zh' ? '加载更早' : 'Load earlier';
    var loadingLabel = language === 'zh' ? '正在加载…' : 'Loading…';
    var errorLabel = language === 'zh' ? '加载失败，重试' : 'Could not load. Retry';

    button.addEventListener('click', async function () {
      var entries = Array.prototype.slice.call(manifest.querySelectorAll(':scope > span')).slice(0, 2);
      if (!entries.length) {
        button.closest('.load-earlier-wrap').remove();
        return;
      }

      button.disabled = true;
      button.textContent = loadingLabel;
      try {
        var loaded = await Promise.all(entries.map(async function (entry) {
          var url = new URL(entry.dataset.url, window.location.href);
          if (url.origin !== window.location.origin) {
            throw new Error('History URL must be same-origin');
          }
          var response = await fetch(url.href, {credentials: 'same-origin'});
          if (!response.ok) throw new Error('History request failed: ' + response.status);
          var markup = await response.text();
          var parsed = new DOMParser().parseFromString(markup, 'text/html');
          var source = (
            parsed.querySelector('[data-feed-fragment]') ||
            parsed.querySelector('.main-content')
          );
          if (!source) throw new Error('History content was not found');
          return createLoadedDay(language, entry.dataset.date, source);
        }));

        loaded.forEach(function (section) {
          stream.appendChild(section);
          enhanceDigest(section.querySelector('.daily-feed-content'));
        });
        entries.forEach(function (entry) {
          entry.remove();
        });

        if (!manifest.querySelector(':scope > span')) {
          button.closest('.load-earlier-wrap').remove();
        } else {
          button.disabled = false;
          button.textContent = idleLabel;
        }
      } catch (error) {
        button.disabled = false;
        button.textContent = errorLabel;
      }
    });
  }

  function setupInterfaceLanguage() {
    interfaceLanguage = normalizeLanguage(document.documentElement.lang);
    applyInterfaceLanguage(interfaceLanguage);
  }

  function systemDark() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function currentDark() {
    var explicit = document.documentElement.dataset.theme;
    return explicit ? explicit === 'dark' : systemDark();
  }

  function updateThemeButtonLabel() {
    var button = document.querySelector('.theme-toggle');
    if (!button) return;
    var dark = currentDark();
    var label = interfaceLanguage === 'en'
      ? (dark ? 'Switch to light mode' : 'Switch to dark mode')
      : (dark ? '切换浅色模式' : '切换深色模式');
    button.textContent = dark ? '☀' : '◐';
    button.setAttribute('aria-label', label);
    button.title = label;
  }

  function applyInterfaceLanguage(language) {
    document.querySelectorAll('[data-i18n-zh][data-i18n-en]').forEach(function (element) {
      element.textContent = element.dataset['i18n' + (language === 'en' ? 'En' : 'Zh')];
    });
    document.querySelectorAll('[data-i18n-aria-zh][data-i18n-aria-en]').forEach(function (element) {
      element.setAttribute(
        'aria-label',
        element.dataset['i18nAria' + (language === 'en' ? 'En' : 'Zh')]
      );
    });
    document.querySelectorAll('[data-i18n-href-zh][data-i18n-href-en]').forEach(function (element) {
      element.setAttribute(
        'href',
        element.dataset['i18nHref' + (language === 'en' ? 'En' : 'Zh')]
      );
    });
    updateThemeButtonLabel();
  }

  function setupThemeToggle() {
    var button = document.querySelector('.theme-toggle');
    if (!button) return;

    button.addEventListener('click', function () {
      var next = currentDark() ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem('bmtnews-theme', next);
      } catch (error) {
        // Storage is an enhancement only.
      }
      updateThemeButtonLabel();
    });

    updateThemeButtonLabel();
  }

  /* Scrollspy: highlight the ranking-rail entry for the story being read. */
  var scrollspyObserver = null;
  var observedArticles = typeof WeakSet === 'function' ? new WeakSet() : null;

  function setActiveHeadline(articleId) {
    if (!articleId) return;
    document.querySelectorAll('.headline-list > li').forEach(function (item) {
      var anchor = item.querySelector('a[href^="#"]');
      var matches = anchor && anchor.getAttribute('href') === '#' + articleId;
      item.classList.toggle('active', Boolean(matches));
    });
  }

  function observeArticles(root) {
    if (!('IntersectionObserver' in window)) return;
    if (!scrollspyObserver) {
      scrollspyObserver = new IntersectionObserver(function (entries) {
        var best = null;
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          if (!best || entry.intersectionRatio > best.intersectionRatio) {
            best = entry;
          }
        });
        if (best) setActiveHeadline(best.target.id);
      }, { rootMargin: '-15% 0px -65% 0px', threshold: [0, 0.25, 0.5, 1] });
    }
    (root || document).querySelectorAll('.digest-item[id]').forEach(function (article) {
      if (observedArticles) {
        if (observedArticles.has(article)) return;
        observedArticles.add(article);
      }
      scrollspyObserver.observe(article);
    });
  }

  function setupScrollspy() {
    observeArticles(document);
    var stream = document.querySelector('.day-stream');
    if (stream && 'MutationObserver' in window) {
      new MutationObserver(function () {
        observeArticles(stream);
      }).observe(stream, { childList: true, subtree: true });
    }
  }

  /* Keyboard navigation: j/k jump between stories, respecting filters. */
  function setupKeyboardNav() {
    document.addEventListener('keydown', function (event) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key !== 'j' && event.key !== 'k') return;
      var target = event.target;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }
      var articles = Array.prototype.filter.call(
        document.querySelectorAll('.digest-item[id]'),
        function (article) {
          return !article.hidden && article.offsetParent !== null;
        }
      );
      if (!articles.length) return;
      var line = 70;
      var current = -1;
      for (var i = 0; i < articles.length; i++) {
        if (articles[i].getBoundingClientRect().top <= line + 1) {
          current = i;
        } else {
          break;
        }
      }
      var next = event.key === 'j'
        ? Math.min(current + 1, articles.length - 1)
        : Math.max(current - 1, 0);
      articles[next].scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    setupThemeToggle();
    setupInterfaceLanguage();
    setupStorySharing();
    enhanceDailyFeeds();
    setupScrollspy();
    setupKeyboardNav();
    document.documentElement.classList.add('feed-ready');
  });
})();
