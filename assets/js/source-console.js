(function () {
  'use strict';

  var root = document.getElementById('source-console');
  if (!root) return;

  var TYPE_LABELS = {
    rss: 'RSS',
    telegram: 'Telegram',
    github: 'GitHub',
    reddit: 'Reddit',
    hackernews: 'Hacker News',
    google_news: 'Google News',
    gdelt: 'GDELT',
    ossinsight: 'OSS Insight'
  };

  var TRACK_LABELS = {
    crypto: 'Crypto',
    technology: 'AI / 科技',
    policy: '政策',
    other: '其他'
  };

  var STATUS_LABELS = {
    active: '启用',
    paused: '暂停',
    'parent-paused': '采集器停用'
  };

  var elements = {
    totalCount: document.getElementById('source-total-count'),
    activeCount: document.getElementById('source-active-count'),
    pausedCount: document.getElementById('source-paused-count'),
    cryptoCount: document.getElementById('source-crypto-count'),
    technologyCount: document.getElementById('source-technology-count'),
    policyCount: document.getElementById('source-policy-count'),
    search: document.getElementById('source-search-input'),
    typeFilter: document.getElementById('source-type-filter'),
    trackFilter: document.getElementById('source-track-filter'),
    statusFilter: document.getElementById('source-status-filter'),
    reset: document.getElementById('source-filter-reset'),
    resultCount: document.getElementById('source-result-count'),
    tableBody: document.getElementById('source-table-body'),
    loading: document.getElementById('source-loading-state'),
    empty: document.getElementById('source-empty-state')
  };

  var state = {
    records: []
  };

  function normalizedUrl(value) {
    var url = new URL(value);
    url.hash = '';
    url.hostname = url.hostname.toLowerCase();
    if (
      (url.protocol === 'https:' && url.port === '443') ||
      (url.protocol === 'http:' && url.port === '80')
    ) {
      url.port = '';
    }
    if (url.pathname !== '/') {
      url.pathname = url.pathname.replace(/\/+$/, '');
    }
    return url.protocol.toLowerCase() + '//' + url.host + url.pathname + url.search;
  }

  function sourceKey(type, source) {
    if (type === 'rss') return 'rss|' + normalizedUrl(source.url);
    if (type === 'telegram') {
      return 'telegram|' + String(source.channel || '').replace(/^@/, '').toLowerCase();
    }
    if (type === 'github') {
      var identity = source.owner && source.repo
        ? source.owner + '/' + source.repo
        : source.username || '';
      return 'github|' + String(source.type || 'repo_releases').toLowerCase() +
        '|' + identity.toLowerCase();
    }
    if (type === 'reddit') {
      return 'reddit|subreddit|' + String(source.subreddit || '').toLowerCase();
    }
    return type + '|main';
  }

  function categoryTrack(category, config) {
    var filtering = config.filtering || {};
    var groups = filtering.category_groups || {};
    var primary = filtering.primary_groups || [];
    var matchedGroup = null;

    Object.keys(groups).some(function (groupName) {
      if ((groups[groupName].categories || []).indexOf(category) !== -1) {
        matchedGroup = groupName;
        return true;
      }
      return false;
    });

    if (matchedGroup && primary.indexOf(matchedGroup) !== -1) return 'crypto';
    if (matchedGroup === 'technology') return 'technology';
    if (matchedGroup === 'regulation') return 'policy';
    return 'other';
  }

  function createRecord(config, values) {
    var itemEnabled = values.enabled !== false;
    var parentEnabled = values.parentEnabled !== false;
    return {
      key: values.key,
      name: values.name,
      type: values.type,
      endpoint: values.endpoint,
      viewUrl: values.viewUrl || '',
      category: values.category || 'other',
      track: categoryTrack(values.category || '', config),
      status: !parentEnabled && itemEnabled
        ? 'parent-paused'
        : itemEnabled ? 'active' : 'paused'
    };
  }

  function flattenSources(config) {
    var sources = config.sources || {};
    var records = [];

    (sources.rss || []).forEach(function (source) {
      records.push(createRecord(config, {
        key: sourceKey('rss', source),
        name: source.name,
        type: 'rss',
        endpoint: source.url,
        viewUrl: source.url,
        category: source.category,
        enabled: source.enabled
      }));
    });

    (sources.github || []).forEach(function (source) {
      var identity = source.owner && source.repo
        ? source.owner + '/' + source.repo
        : source.username || 'GitHub source';
      records.push(createRecord(config, {
        key: sourceKey('github', source),
        name: identity,
        type: 'github',
        endpoint: identity,
        viewUrl: 'https://github.com/' + identity,
        category: source.category,
        enabled: source.enabled
      }));
    });

    var telegram = sources.telegram || {};
    (telegram.channels || []).forEach(function (source) {
      var channel = String(source.channel || '').replace(/^@/, '');
      records.push(createRecord(config, {
        key: sourceKey('telegram', source),
        name: '@' + channel,
        type: 'telegram',
        endpoint: channel,
        viewUrl: 'https://t.me/' + channel,
        category: source.category,
        enabled: source.enabled,
        parentEnabled: telegram.enabled
      }));
    });

    var reddit = sources.reddit || {};
    (reddit.subreddits || []).forEach(function (source) {
      var subreddit = String(source.subreddit || '');
      records.push(createRecord(config, {
        key: sourceKey('reddit', source),
        name: 'r/' + subreddit,
        type: 'reddit',
        endpoint: subreddit,
        viewUrl: 'https://www.reddit.com/r/' + subreddit + '/',
        category: source.category,
        enabled: source.enabled,
        parentEnabled: reddit.enabled
      }));
    });

    [
      ['hackernews', 'Hacker News', 'https://news.ycombinator.com/'],
      ['google_news', 'Google News Search', ''],
      ['gdelt', 'GDELT Search', ''],
      ['ossinsight', 'OSS Insight Trending', 'https://ossinsight.io/']
    ].forEach(function (definition) {
      var type = definition[0];
      var source = sources[type];
      if (!source) return;
      var endpoint = source.query || (source.keywords || []).join(', ') || 'main';
      records.push(createRecord(config, {
        key: sourceKey(type, source),
        name: definition[1],
        type: type,
        endpoint: endpoint,
        viewUrl: definition[2],
        category: source.category,
        enabled: source.enabled
      }));
    });

    var trackOrder = {crypto: 0, policy: 1, technology: 2, other: 3};
    records.sort(function (left, right) {
      if (left.status === 'active' && right.status !== 'active') return -1;
      if (left.status !== 'active' && right.status === 'active') return 1;
      if (trackOrder[left.track] !== trackOrder[right.track]) {
        return trackOrder[left.track] - trackOrder[right.track];
      }
      return left.name.localeCompare(right.name, 'zh-CN');
    });
    return records;
  }

  function setText(element, value) {
    if (element) element.textContent = String(value);
  }

  function updateMetrics(records) {
    var active = records.filter(function (record) {
      return record.status === 'active';
    });
    setText(elements.totalCount, records.length);
    setText(elements.activeCount, active.length);
    setText(elements.pausedCount, records.length - active.length);
    setText(elements.cryptoCount, active.filter(function (record) {
      return record.track === 'crypto';
    }).length);
    setText(elements.technologyCount, active.filter(function (record) {
      return record.track === 'technology';
    }).length);
    setText(elements.policyCount, active.filter(function (record) {
      return record.track === 'policy';
    }).length);
  }

  function addCell(row, label, className) {
    var cell = document.createElement('td');
    cell.dataset.label = label;
    if (className) cell.className = className;
    row.appendChild(cell);
    return cell;
  }

  function sourceLink(record) {
    if (!record.viewUrl) {
      var text = document.createElement('small');
      text.textContent = record.endpoint;
      return text;
    }
    var link = document.createElement('a');
    link.href = record.viewUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = record.endpoint;
    link.title = record.endpoint;
    return link;
  }

  function buildRow(record) {
    var row = document.createElement('tr');

    var main = addCell(row, '来源', 'source-main-cell');
    var name = document.createElement('strong');
    name.textContent = record.name;
    main.appendChild(name);
    main.appendChild(sourceLink(record));

    var type = addCell(row, '类型');
    var typePill = document.createElement('span');
    typePill.className = 'source-type-pill';
    typePill.textContent = TYPE_LABELS[record.type] || record.type;
    type.appendChild(typePill);

    var track = addCell(row, '方向');
    var trackPill = document.createElement('span');
    trackPill.className = 'source-track-pill';
    trackPill.dataset.track = record.track;
    trackPill.textContent = TRACK_LABELS[record.track] || record.track;
    track.appendChild(trackPill);

    var category = addCell(row, '分类');
    category.textContent = record.category;

    var status = addCell(row, '状态');
    var statusPill = document.createElement('span');
    statusPill.className = 'source-status-pill';
    statusPill.dataset.status = record.status;
    statusPill.textContent = STATUS_LABELS[record.status] || record.status;
    status.appendChild(statusPill);

    var actions = addCell(row, '操作', 'source-row-actions');
    var copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'source-row-action';
    copy.dataset.copyKey = record.key;
    copy.textContent = '复制来源键';
    actions.appendChild(copy);

    return row;
  }

  function filteredRecords() {
    var query = (elements.search.value || '').trim().toLowerCase();
    var type = elements.typeFilter.value;
    var track = elements.trackFilter.value;
    var status = elements.statusFilter.value;

    return state.records.filter(function (record) {
      var haystack = [
        record.name,
        record.endpoint,
        record.category,
        record.key
      ].join(' ').toLowerCase();
      return (!query || haystack.indexOf(query) !== -1) &&
        (type === 'all' || record.type === type) &&
        (track === 'all' || record.track === track) &&
        (status === 'all' || record.status === status);
    });
  }

  function render() {
    var records = filteredRecords();
    elements.tableBody.textContent = '';
    records.forEach(function (record) {
      elements.tableBody.appendChild(buildRow(record));
    });
    elements.empty.hidden = records.length !== 0;
    setText(elements.resultCount, '显示 ' + records.length + ' / ' + state.records.length + ' 个来源');
  }

  function populateTypes(records) {
    var types = {};
    records.forEach(function (record) {
      types[record.type] = true;
    });
    Object.keys(types).sort().forEach(function (type) {
      var option = document.createElement('option');
      option.value = type;
      option.textContent = TYPE_LABELS[type] || type;
      elements.typeFilter.appendChild(option);
    });
  }

  function copySourceKey(button) {
    var key = button.dataset.copyKey;
    if (!key) return;

    function showCopied() {
      var original = button.textContent;
      button.textContent = '已复制';
      window.setTimeout(function () {
        button.textContent = original;
      }, 1600);
    }

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(key).then(showCopied);
      return;
    }

    var input = document.createElement('textarea');
    input.value = key;
    input.setAttribute('readonly', '');
    input.style.position = 'fixed';
    input.style.opacity = '0';
    document.body.appendChild(input);
    input.select();
    document.execCommand('copy');
    input.remove();
    showCopied();
  }

  function bindEvents() {
    [elements.search, elements.typeFilter, elements.trackFilter, elements.statusFilter]
      .forEach(function (element) {
        element.addEventListener(element.tagName === 'INPUT' ? 'input' : 'change', render);
      });

    elements.reset.addEventListener('click', function () {
      elements.search.value = '';
      elements.typeFilter.value = 'all';
      elements.trackFilter.value = 'all';
      elements.statusFilter.value = 'all';
      render();
    });

    elements.tableBody.addEventListener('click', function (event) {
      var button = event.target.closest('[data-copy-key]');
      if (button) copySourceKey(button);
    });
  }

  function showLoadError() {
    elements.loading.hidden = true;
    elements.empty.hidden = false;
    elements.empty.textContent = '暂时无法读取生产配置，请稍后重试或查看原始配置。';
    setText(elements.resultCount, '读取失败');
  }

  fetch(root.dataset.configUrl, {cache: 'no-store'})
    .then(function (response) {
      if (!response.ok) throw new Error('Config request failed');
      return response.json();
    })
    .then(function (config) {
      state.records = flattenSources(config);
      updateMetrics(state.records);
      populateTypes(state.records);
      bindEvents();
      elements.loading.hidden = true;
      render();
    })
    .catch(showLoadError);
})();
