/** Gift Money Management - Frontend (refactored) */
/* ── State ── */
const API = window.APP_CONFIG?.API_BASE || '';
let currentUser = null;
let token = localStorage.getItem('gift_token');
let currentPage = 1;
const pageSize = 20;
let pendingExcelData = null;
let isMobile = window.innerWidth <= 768;  // 移动端检测

/* ── Utils ── */
function fmt(n) {
  const num = Number(n);
  if (isNaN(num) || !isFinite(num)) return '¥0.00';
  return '¥' + num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function tagClass(cat) {
  if (!cat) return 'tag-other';
  if (cat.includes('婚')) return 'tag-marriage';
  if (cat.includes('葬')) return 'tag-funeral';
  if (cat.includes('生日')) return 'tag-birthday';
  if (cat.includes('乔迁') || cat.includes('开业')) return 'tag-house';
  return 'tag-other';
}

function showToast(msg, type = 'success') {
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}

/* ── Import Loading Overlay ── */
function showImportLoading(text = '正在导入...') {
  let overlay = document.getElementById('import-loading-overlay');
  if (!overlay) {
    overlay = el('div', { id: 'import-loading-overlay', className: 'import-loading-overlay' },
      el('div', { className: 'import-loading-content' },
        el('div', { className: 'import-spinner' }),
        el('div', { className: 'import-loading-text' }, text),
        el('div', { className: 'import-loading-hint' }, '请稍候，导入完成前请勿关闭页面')
      )
    );
    document.body.appendChild(overlay);
  } else {
    overlay.querySelector('.import-loading-text').textContent = text;
    overlay.style.display = 'flex';
  }
}

function hideImportLoading() {
  const overlay = document.getElementById('import-loading-overlay');
  if (overlay) {
    overlay.style.display = 'none';
  }
}

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'className') e.className = v;
    else if (k === 'dataset') Object.entries(v).forEach(([dk, dv]) => e.dataset[dk] = dv);
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else e.setAttribute(k, v);
  });
  for (const c of children) {
    if (c == null) continue;
    e.append(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return e;
}

/* ── Auth ── */
function switchLoginTab(tab) {
  document.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
  document.querySelector('.login-tab:nth-child(' + (tab === 'login' ? '1' : '2') + ')').classList.add('active');
  document.getElementById('login-form').style.display = tab === 'login' ? 'flex' : 'none';
  document.getElementById('register-form').style.display = tab === 'register' ? 'flex' : 'none';
}

function enterApp() {
  document.getElementById('login-page').style.display = 'none';
  document.getElementById('app').style.display = 'block';
  document.getElementById('user-name').textContent = currentUser?.display_name || '用户';
  document.getElementById('mobile-user-name').textContent = currentUser?.display_name || '用户';

  // 根据设备显示不同的导航
  if (isMobile) {
    document.getElementById('mobile-nav').style.display = 'flex';
    document.getElementById('user-menu').style.display = 'none';
  } else {
    document.getElementById('mobile-nav').style.display = 'none';
    document.getElementById('user-menu').style.display = 'block';
  }

  loadCategories();
  loadSummary();
  loadTransactions(1);
}

function showTabMobile(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.style.display = 'none');
  document.querySelectorAll('.mobile-nav-item').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).style.display = 'block';
  event.target.closest('.mobile-nav-item').classList.add('active');
  if (name === 'summary') loadSummary();
  if (name === 'people') loadPersonList();
  if (name === 'list') loadCategories();
}

function showMobileUserMenu() {
  document.getElementById('mobile-user-modal').classList.add('show');
}

// 监听窗口大小变化
window.addEventListener('resize', () => {
  const wasMobile = isMobile;
  isMobile = window.innerWidth <= 768;

  // 如果设备类型变化，重新渲染
  if (wasMobile !== isMobile && document.getElementById('app').style.display !== 'none') {
    if (isMobile) {
      document.getElementById('mobile-nav').style.display = 'flex';
      document.getElementById('user-menu').style.display = 'none';
    } else {
      document.getElementById('mobile-nav').style.display = 'none';
      document.getElementById('user-menu').style.display = 'block';
    }
    // 重新渲染当前列表
    loadTransactions(currentPage);
  }
});

function logout() {
  token = null;
  currentUser = null;
  localStorage.removeItem('gift_token');
  localStorage.removeItem('gift_user');
  document.getElementById('login-page').style.display = 'flex';
  document.getElementById('app').style.display = 'none';
  document.getElementById('user-menu').style.display = 'none';
}

/* ── API ── */
async function api(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...opts.headers };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  try {
    const res = await fetch(url, { ...opts, headers, body: opts.body });
    // 登录接口返回401表示账密错误，不触发logout
    if (res.status === 401 && !url.includes('/auth/login')) {
      showToast('登录已过期，请重新登录', 'error');
      logout();
      return null;
    }
    return res;
  } catch (e) {
    console.error('API请求失败:', url, e);
    showToast('网络请求失败，请检查连接', 'error');
    return null;
  }
}

/* ── Summary ── */
async function loadSummary() {
  const res = await api(API + '/api/stats/summary');
  if (!res) return;
  const d = await res.json();
  document.getElementById('total-income').textContent = fmt(d.total_income);
  document.getElementById('total-expense').textContent = fmt(d.total_expense);
  const netEl = document.getElementById('net-balance');
  const netCard = document.getElementById('net-card');
  const netVal = Number(d.balance) || 0;
  netEl.textContent = (netVal >= 0 ? '+' : '') + fmt(netVal);
  netCard.className = 'summary-card net ' + (netVal >= 0 ? 'positive' : 'negative');
  document.getElementById('income-count').textContent = d.income_count;
  document.getElementById('expense-count').textContent = d.expense_count;

  // Category charts
  renderBarChart('cat-income-chart', d.category_income || [], 'income');
  renderBarChart('cat-expense-chart', d.category_expense || [], 'expense');

  // Monthly
  const monthlyEl = document.getElementById('monthly-chart');
  monthlyEl.innerHTML = (d.monthly || []).map(r => {
    const income = Number(r.income) || 0;
    const expense = Number(r.expense) || 0;
    const net = income + expense; // expense is negative
    const total = income + Math.abs(expense) || 1;
    const incPct = (income / total) * 100;
    const expPct = (Math.abs(expense) / total) * 100;
    return `<div class="bar-item">
      <span class="bar-label">${r.month}</span>
      <div class="bar-track"><div class="bar-split">
        <div class="bar-fill income" style="width:${incPct}%"></div>
        <div class="bar-fill expense" style="width:${expPct}%"></div>
      </div></div>
      <span class="bar-value" style="color:${net>=0?'var(--income)':'var(--expense)'}">${net>=0?'+':''}${fmt(net)}</span>
    </div>`;
  }).join('') || '<div class="empty-state"><div class="icon">📅</div><p>暂无数据</p></div>';

  // Person stats
  const personEl = document.getElementById('person-stats');
  personEl.innerHTML = (d.person_stats || []).map(r => {
    const total_income = Number(r.total_income) || 0;
    const total_expense = Number(r.total_expense) || 0;
    const balance = Number(r.balance) || 0;
    return `<tr><td>${r.name}</td><td class="amount-income">${fmt(total_income)}</td>
         <td class="amount-expense">${fmt(total_expense)}</td>
         <td class="${balance>=0?'amount-income':'amount-expense'}">${fmt(balance)}</td>
         <td>${r.cnt}</td>
         <td><button class="btn btn-sm btn-primary" onclick="viewPersonDetail(${r.id})">查看</button></td></tr>`;
  }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:32px;">暂无数据</td></tr>';
}

function renderBarChart(id, data, type) {
  const el = document.getElementById(id);
  const max = (data.reduce((m, r) => Math.max(m, Number(r.total) || 0), 0)) || 1;
  el.innerHTML = data.map(r => {
    const val = Number(r.total) || 0;
    const pct = max > 0 ? Math.max((val / max) * 100, 2) : 2;
    return `<div class="bar-item">
      <span class="bar-label">${r.category}</span>
      <div class="bar-track"><div class="bar-fill ${type}" style="width:${pct}%"></div></div>
      <span class="bar-value amount-${type}">${fmt(val)}</span>
    </div>`;
  }).join('') || '<div class="empty-state"><div class="icon">📊</div><p>暂无数据</p></div>';
}

/* ── Person Detail ── */
async function viewPersonDetail(id) {
  const res = await api(API + '/api/stats/person/' + id);
  if (!res) return;
  const d = await res.json();
  if (d.error) { showToast(d.error, 'error'); return; }
  document.getElementById('person-modal-title').textContent = '👤 ' + d.name;
  const pBal = Number(d.balance) || 0;
  const pInc = Number(d.total_income) || 0;
  const pExp = Number(d.total_expense) || 0;
  let html = `<div class="summary-grid" style="margin-bottom:16px;">
    <div class="summary-card net ${pBal>=0?'positive':'negative'}">
      <div class="label">净余额</div><div class="value">${fmt(pBal)}</div></div>
    <div class="summary-card income"><div class="label">总收礼</div><div class="value">${fmt(pInc)}</div></div>
    <div class="summary-card expense"><div class="label">总送礼</div><div class="value">${fmt(pExp)}</div></div>
  </div>`;
  if (d.phone || d.address || d.note) {
    html += `<div style="margin-bottom:12px;color:var(--text-secondary);font-size:0.9rem;">`;
    if (d.phone) html += '📱 ' + d.phone + '<br>';
    if (d.address) html += '📍 ' + d.address + '<br>';
    if (d.note) html += '📝 ' + d.note;
    html += '</div>';
  }
  html += '<div class="table-wrapper"><table><thead><tr><th>日期</th><th>人名</th><th>分类</th><th>金额</th><th>方向</th><th>备注</th></tr></thead><tbody>';
  html += (d.transactions || []).map(r =>
    `<tr><td>${r.date}</td><td>${r.name}</td>
     <td><span class="tag ${tagClass(r.category)}">${r.category}</span></td>
     <td class="${r.direction==='income'?'amount-income':'amount-expense'}">${r.direction==='income'?'+':'-'}${fmt(r.amount)}</td>
     <td>${r.direction==='income'?'收礼':'送礼'}</td>
     <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${(r.note||'').replace(/"/g,'&quot;')}">${r.note||'-'}</td></tr>`
  ).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:32px;">无记录</td></tr>';
  html += '</tbody></table></div>';
  document.getElementById('person-modal-body').innerHTML = html;
  document.getElementById('person-modal').classList.add('show');
}

/* ── Transactions ── */
let currentSort = { field: 'date', order: 'desc' }; // 默认日期倒序

function toggleSort(field) {
  if (currentSort.field === field) {
    currentSort.order = currentSort.order === 'desc' ? 'asc' : 'desc';
  } else {
    currentSort.field = field;
    currentSort.order = 'desc';
  }
  updateSortIcon();
  loadTransactions(1);
}

function updateSortIcon() {
  const icon = document.getElementById('sort-date-icon');
  if (icon) {
    icon.textContent = currentSort.order === 'desc' ? '↓' : '↑';
  }
}

async function loadTransactions(page) {
  currentPage = page;
  const params = new URLSearchParams({ page: page, size: pageSize });
  const name = document.getElementById('filter-name').value;
  const category = document.getElementById('filter-category').value;
  const dateStart = document.getElementById('filter-date-start').value;
  const dateEnd = document.getElementById('filter-date-end').value;
  const direction = document.getElementById('filter-direction').value;
  if (name) params.set('name', name);
  if (category) params.set('category', category);
  if (dateStart) params.set('date_start', dateStart);
  if (dateEnd) params.set('date_end', dateEnd);
  if (direction) params.set('direction', direction);
  params.set('sort', currentSort.field);
  params.set('order', currentSort.order);

  const res = await api(API + '/api/transactions?' + params);
  if (!res) return;
  const data = await res.json();

  if (isMobile) {
    // 移动端：卡片列表
    const container = document.getElementById('tx-card-container');
    container.style.display = 'block';
    document.querySelector('.table-wrapper.desktop-only').style.display = 'none';
    container.innerHTML = '';

    if ((data.data || []).length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="icon">📋</div><p>暂无记录</p></div>';
    } else {
      const cardList = el('div', { className: 'mobile-card-list' });
      (data.data || []).forEach(r => {
        const amt = Number(r.amount) || 0;
        const card = el('div', { className: 'mobile-tx-card' },
          el('div', { className: 'mobile-tx-card-header' },
            el('div', { className: 'mobile-tx-card-name' }, r.name),
            el('div', { className: `mobile-tx-card-amount ${r.direction==='income'?'amount-income':'amount-expense'}` },
              (r.direction==='income'?'+':'-') + fmt(amt))
          ),
          el('div', { className: 'mobile-tx-card-meta' },
            el('span', {}, `📅 ${r.date}`),
            el('span', {}, `🏷️ ${r.category}`),
            el('span', {}, r.direction==='income'?'📥 收礼':'📤 送礼')
          ),
          el('div', { className: 'mobile-tx-card-actions' },
            el('button', { className: 'btn btn-secondary', onclick: () => editTransaction(r.id) }, '编辑'),
            el('button', { className: 'btn btn-danger', onclick: () => deleteTransaction(r.id) }, '删除')
          )
        );
        cardList.appendChild(card);
      });
      container.appendChild(cardList);
    }
  } else {
    // Web端：表格
    document.getElementById('tx-card-container').style.display = 'none';
    document.querySelector('.table-wrapper.desktop-only').style.display = 'block';
    const tbody = document.getElementById('tx-table-body');
    tbody.innerHTML = (data.data || []).map(r => {
      const amt = Number(r.amount) || 0;
      const address = r.person_address || '';
      return `<tr data-id="${r.id}">
        <td>${r.date}</td><td>${r.name}</td>
        <td style="max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${address}">${address || '-'}</td>
        <td><span class="tag ${tagClass(r.category)}">${r.category}</span></td>
        <td class="${r.direction==='income'?'amount-income':'amount-expense'}">${r.direction==='income'?'+':'-'}${fmt(amt)}</td>
        <td>${r.direction==='income'?'收礼':'送礼'}</td>
        <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${(r.note||'').replace(/"/g,'&quot;')}">${r.note||'-'}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="editTransaction(${r.id})">编辑</button>
          <button class="btn btn-sm btn-danger" onclick="deleteTransaction(${r.id})">删除</button>
        </td></tr>`;
    }).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:32px;">暂无记录</td></tr>';
  }

  document.getElementById('pagination').innerHTML = `
    <button class="page-btn" onclick="loadTransactions(${page - 1})" ${page <= 1 ? 'disabled' : ''}>上一页</button>
    <span style="line-height:36px;color:var(--text-secondary);font-size:0.88rem;">第 ${page} 页 / 共 ${Math.ceil((data.total||0) / pageSize)} 页</span>
    <button class="page-btn" onclick="loadTransactions(${page + 1})" ${(data.data||[]).length < pageSize ? 'disabled' : ''}>下一页</button>`;
}

async function addTransaction(e) {
  e.preventDefault();
  const form = document.getElementById('tx-form');
  const fd = new FormData(form);
  const obj = Object.fromEntries(fd.entries());

  // 验证必填字段
  if (!obj.name || !obj.name.trim()) {
    showToast('请输入姓名', 'error');
    return;
  }
  if (!obj.amount || parseFloat(obj.amount) <= 0) {
    showToast('请输入有效金额', 'error');
    return;
  }
  if (!obj.category) {
    showToast('请选择分类', 'error');
    return;
  }
  if (!obj.date) {
    showToast('请选择日期', 'error');
    return;
  }

  obj.amount = parseFloat(obj.amount);
  const pid = document.getElementById('tx-person-id').value;
  if (pid) obj.person_id = parseInt(pid);

  const res = await api(API + '/api/transactions', { method: 'POST', body: JSON.stringify(obj) });
  if (!res) return;
  if (res.ok) {
    showToast('添加成功');
    form.reset();
    document.getElementById('tx-person-id').value = '';
    document.querySelector('[name="date"]').value = new Date().toISOString().slice(0, 10);
    loadTransactions(1);
    loadSummary();
  } else {
    const err = await res.json().catch(() => ({}));
    // 处理422验证错误
    const msg = err.detail?.msg || err.detail || '添加失败';
    showToast(msg, 'error');
  }
}

async function editTransaction(id) {
  const res = await api(API + '/api/transactions/' + id);
  if (!res) return;
  const tx = await res.json();
  document.getElementById('edit-id').value = tx.id;
  document.getElementById('edit-name').value = tx.name;
  document.getElementById('edit-amount').value = tx.amount;
  document.getElementById('edit-category').value = tx.category;
  document.getElementById('edit-date').value = tx.date;
  document.getElementById('edit-direction').value = tx.direction;
  document.getElementById('edit-note').value = tx.note || '';
  document.getElementById('edit-person-id').value = tx.person_id || '';
  document.getElementById('edit-modal').classList.add('show');
}

async function saveEdit() {
  const id = document.getElementById('edit-id').value;
  const obj = {
    name: document.getElementById('edit-name').value,
    amount: parseFloat(document.getElementById('edit-amount').value),
    category: document.getElementById('edit-category').value,
    date: document.getElementById('edit-date').value,
    direction: document.getElementById('edit-direction').value,
    note: document.getElementById('edit-note').value,
  };
  const pid = document.getElementById('edit-person-id').value;
  if (pid) obj.person_id = parseInt(pid);
  const res = await api(API + '/api/transactions/' + id, { method: 'PUT', body: JSON.stringify(obj) });
  if (!res) return;
  if (res.ok) {
    showToast('更新成功');
    document.getElementById('edit-modal').classList.remove('show');
    loadTransactions(currentPage);
    loadSummary();
  } else {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || '更新失败', 'error');
  }
}

async function deleteTransaction(id) {
  if (!confirm('确定删除此记录？')) return;
  const res = await api(API + '/api/transactions/' + id, { method: 'DELETE' });
  if (!res) return;
  if (res.ok) {
    showToast('删除成功');
    loadTransactions(currentPage);
    loadSummary();
  }
}

/* ── Categories ── */
async function loadCategories() {
  const res = await api(API + '/api/categories');
  if (!res) return;
  const cats = await res.json();
  const opts = cats.map(c => `<option value="${c.name}">${c.name}</option>`).join('');
  document.getElementById('form-category').innerHTML = '<option value="">请选择</option>' + opts;
  document.getElementById('edit-category').innerHTML = '<option value="">请选择</option>' + opts;
  const filterSel = document.getElementById('filter-category');
  const curVal = filterSel.value;
  filterSel.innerHTML = '<option value="">全部</option>' + opts;
  filterSel.value = curVal;

  document.getElementById('category-list').innerHTML = cats.length
    ? cats.map(c => `<span class="category-item"><span class="tag ${tagClass(c.name)}">${c.name}</span></span>`).join('')
    : '<div class="empty-state"><p>暂无分类</p></div>';
}

async function addCategory(e) {
  e.preventDefault();
  const name = document.getElementById('cat-name').value.trim();
  if (!name) { showToast('请填写分类名称', 'error'); return; }
  const res = await api(API + '/api/categories', { method: 'POST', body: JSON.stringify({ name }) });
  if (!res) return;
  if (res.ok) {
    showToast('分类创建成功');
    document.getElementById('cat-form').reset();
    loadCategories();
  } else {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || '创建失败', 'error');
  }
}

/* ── Quick Add Category (inline) ── */
async function quickAddCategory(selectId) {
  // 存储目标选择框ID
  window._categoryTargetSelect = selectId;
  // 打开抽屉
  openDrawer('add-category-drawer');
  document.getElementById('drawer-category-name').value = '';
  document.getElementById('drawer-category-name').focus();
}

async function submitAddCategory() {
  const name = document.getElementById('drawer-category-name').value.trim();
  if (!name) {
    showToast('请输入分类名称', 'error');
    return;
  }

  const res = await api(API + '/api/categories', {
    method: 'POST',
    body: JSON.stringify({ name })
  });

  if (!res) return;

  if (res.ok) {
    showToast('分类创建成功');
    await loadCategories();
    // 自动选中新创建的分类
    if (window._categoryTargetSelect) {
      document.getElementById(window._categoryTargetSelect).value = name;
    }
    closeDrawer('add-category-drawer');
  } else {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || '创建失败', 'error');
  }
}

/* ── Quick Add Person (inline) ── */
let _personCallback = null;

async function quickAddPersonWithName(name) {
  // 存储初始人名，打开抽屉
  openDrawer('add-person-drawer');
  document.getElementById('drawer-person-name').value = name || '';
  document.getElementById('drawer-person-phone').value = '';
  document.getElementById('drawer-person-address').value = '';
  document.getElementById('drawer-person-note').value = '';
  document.getElementById('drawer-person-name').focus();
  // 设置回调：创建成功后填入表单
  _personCallback = (data) => {
    document.getElementById('tx-name').value = data.name;
    document.getElementById('tx-person-id').value = data.id;
    document.getElementById('person-dropdown').style.display = 'none';
  };
}

async function quickAddPersonWithNameForEdit(name) {
  openDrawer('add-person-drawer');
  document.getElementById('drawer-person-name').value = name || '';
  document.getElementById('drawer-person-phone').value = '';
  document.getElementById('drawer-person-address').value = '';
  document.getElementById('drawer-person-note').value = '';
  document.getElementById('drawer-person-name').focus();
  // 设置回调：创建成功后填入编辑表单
  _personCallback = (data) => {
    document.getElementById('edit-name').value = data.name;
    document.getElementById('edit-person-id').value = data.id;
    document.getElementById('edit-person-dropdown').style.display = 'none';
  };
}

/* ── Person Search (Add form) ── */
function searchPersonForTx() {
  const q = document.getElementById('tx-name').value.trim();
  const dropdown = document.getElementById('person-dropdown');
  clearTimeout(searchPersonForTx.timer);
  if (!q || q.length < 1) { dropdown.style.display = 'none'; dropdown.innerHTML = ''; return; }
  searchPersonForTx.timer = setTimeout(async () => {
    const res = await api(API + '/api/people/search?q=' + encodeURIComponent(q));
    if (!res) return;
    const people = await res.json();

    // 构建下拉列表内容
    let html = '';
    if (people.length) {
      html = people.map(p =>
        `<div class="person-suggestion-item" data-id="${p.id}" data-name="${p.name}">
          <span class="person-suggestion-name">${p.name}</span>
          <span class="person-suggestion-meta">${p.phone||'无电话'} · ${p.address||'无地址'}</span>
        </div>`
      ).join('');
    }
    // 始终显示"新增人员"选项
    html += `<div class="person-suggestion-item person-add-new" onclick="quickAddPersonWithName('${q}')">
      <span class="person-suggestion-name">+ 新增人员</span>
      <span class="person-suggestion-meta">"${q}"</span>
    </div>`;

    dropdown.innerHTML = html;
    dropdown.style.display = 'block';
    // 只给已有人员选项添加点击事件（排除新增人员选项）
    dropdown.querySelectorAll('.person-suggestion-item:not(.person-add-new)').forEach(item => {
      item.addEventListener('click', () => {
        document.getElementById('tx-name').value = item.dataset.name;
        document.getElementById('tx-person-id').value = item.dataset.id;
        dropdown.style.display = 'none';
      });
    });
  }, 300);
}

/* ── Person Search (Edit form) ── */
function searchPersonForEdit() {
  const q = document.getElementById('edit-name').value.trim();
  const dropdown = document.getElementById('edit-person-dropdown');
  clearTimeout(searchPersonForEdit.timer);
  if (!q || q.length < 1) { dropdown.style.display = 'none'; dropdown.innerHTML = ''; return; }
  searchPersonForEdit.timer = setTimeout(async () => {
    const res = await api(API + '/api/people/search?q=' + encodeURIComponent(q));
    if (!res) return;
    const people = await res.json();

    let html = '';
    if (people.length) {
      html = people.map(p =>
        `<div class="person-suggestion-item" data-id="${p.id}" data-name="${p.name}">
          <span class="person-suggestion-name">${p.name}</span>
          <span class="person-suggestion-meta">${p.phone||'无电话'} · ${p.address||'无地址'}</span>
        </div>`
      ).join('');
    }
    html += `<div class="person-suggestion-item person-add-new" onclick="quickAddPersonWithNameForEdit('${q}')">
      <span class="person-suggestion-name">+ 新增人员</span>
      <span class="person-suggestion-meta">"${q}"</span>
    </div>`;

    dropdown.innerHTML = html;
    dropdown.style.display = 'block';
    dropdown.querySelectorAll('.person-suggestion-item:not(.person-add-new)').forEach(item => {
      item.addEventListener('click', () => {
        document.getElementById('edit-name').value = item.dataset.name;
        document.getElementById('edit-person-id').value = item.dataset.id;
        dropdown.style.display = 'none';
      });
    });
  }, 300);
}

/* Click outside to close dropdowns */
document.addEventListener('click', (e) => {
  const dd1 = document.getElementById('person-dropdown');
  const txName = document.getElementById('tx-name');
  if (txName && dd1 && !txName.contains(e.target) && !dd1.contains(e.target)) dd1.style.display = 'none';
  const dd2 = document.getElementById('edit-person-dropdown');
  const editName = document.getElementById('edit-name');
  if (editName && dd2 && !editName.contains(e.target) && !dd2.contains(e.target)) dd2.style.display = 'none';
  const menu = document.getElementById('user-menu');
  if (menu && !menu.contains(e.target)) document.getElementById('user-dropdown').style.display = 'none';
});

/* ── Person List ── */
async function loadPersonList(name) {
  let url = API + '/api/people';
  if (name) {
    url += '?name=' + encodeURIComponent(name);
  }
  const res = await api(url);
  if (!res) return;
  const people = await res.json();
  document.getElementById('person-list-body').innerHTML = people.length
    ? people.map(p => {
        const tInc = Number(p.total_income) || 0;
        const tExp = Number(p.total_expense) || 0;
        const bal = Number(p.balance) || 0;
        return `<tr><td><strong>${p.name}</strong></td>
         <td style="color:var(--text-secondary);font-size:0.85rem;">${p.phone||'-'}</td>
         <td style="color:var(--text-secondary);font-size:0.85rem;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${(p.address||'').replace(/"/g,'&quot;')}">${p.address||'-'}</td>
         <td style="color:var(--text-secondary);font-size:0.85rem;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${(p.note||'').replace(/"/g,'&quot;')}">${p.note||'-'}</td>
         <td class="amount-income">${fmt(tInc)}</td>
         <td class="amount-expense">${fmt(tExp)}</td>
         <td class="${bal>=0?'amount-income':'amount-expense'}">${fmt(bal)}</td>
         <td>${p.cnt || 0}</td>
         <td>
           <button class="btn btn-sm btn-secondary" onclick="editPerson(${p.id})">编辑</button>
           <button class="btn btn-sm btn-danger" onclick="confirmDeletePerson(${p.id}, '${p.name}', ${p.cnt || 0})">删除</button>
         </td></tr>`;
      }).join('')
    : '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:32px;">暂无人员</td></tr>';
}

function searchPeople() {
  const name = document.getElementById('person-search').value.trim();
  loadPersonList(name);
}

/* ── Excel Export ── */
async function exportExcel() {
  const res = await api(API + '/api/export/excel');
  if (!res) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = '礼簿记录_' + new Date().toISOString().slice(0, 10) + '.xlsx';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast('导出成功');
}

/* ── Excel Import Preview ── */
async function previewExcel(input) {
  const file = input.files[0];
  if (!file) return;
  document.getElementById('excel-file-name').textContent = file.name;
  showImportLoading('正在解析Excel...');
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch(API + '/api/import/excel-preview', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + token },
    body: fd,
  });
  hideImportLoading();
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || '解析失败', 'error');
    input.value = '';
    document.getElementById('excel-file-name').textContent = '';
    return;
  }
  const data = await res.json();

  // 如果需要确认地址（有同名记录）
  if (data.need_address_confirm) {
    // 保存文件数据供后续使用
    const fileData = await fileToBase64(file);
    window._importFileData = fileData;
    showAddressConfirmModal(data.same_name_records);
    return;
  }

  // 正常流程
  pendingExcelData = data.data;
  let countText = `共 ${data.total} 条 | 需确认 ${data.needs_confirm} 条 | 新人 ${data.new_persons} 条`;
  document.getElementById('excel-preview-count').textContent = countText;
  document.getElementById('excel-preview-area').style.display = 'block';
  renderExcelPreview(pendingExcelData);
}

async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function showAddressConfirmModal(sameNameRecords) {
  // 创建地址确认弹窗
  let modalHtml = `
    <div class="modal-overlay show" id="address-confirm-modal">
      <div class="modal" style="max-width:800px;max-height:90vh;overflow-y:auto;">
        <div class="modal-title">⚠️ 同名人员确认</div>
        <div style="padding:16px;">
          <p style="color:var(--text-secondary);margin-bottom:16px;">
            发现同名记录，请确认每条记录的人员：<br>
            • 填写相同地址 = 同一人<br>
            • 填写不同地址 = 不同人<br>
            • 可选择已有人员直接关联
          </p>
  `;

  sameNameRecords.forEach((group, gIdx) => {
    modalHtml += `
      <div style="margin-bottom:24px;padding:16px;background:var(--bg-secondary);border-radius:8px;">
        <div style="font-weight:600;margin-bottom:12px;color:var(--primary);">
          "${group.name}" - 共 ${group.count} 条记录
        </div>
    `;

    // 如果数据库中有同名人员，显示选择列表
    if (group.existing_people && group.existing_people.length > 0) {
      modalHtml += `
        <div style="margin-bottom:12px;">
          <div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:8px;">已有同名人员（点击可关联）：</div>
          <div style="display:flex;flex-wrap:wrap;gap:8px;">
      `;
      group.existing_people.forEach(p => {
        const balanceText = p.balance >= 0 ? `+¥${p.balance}` : `-¥${Math.abs(p.balance)}`;
        modalHtml += `
          <button class="existing-person-btn" data-group-idx="${gIdx}" data-person-id="${p.id}"
            style="padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;cursor:pointer;text-align:left;">
            <div style="font-weight:600;">${p.name}</div>
            <div style="font-size:0.75rem;color:var(--text-secondary);">${p.address || '无地址'}</div>
            <div style="font-size:0.75rem;color:var(--text-secondary);">往来${p.tx_count}笔 ${balanceText}</div>
          </button>
        `;
      });
      modalHtml += `
          </div>
        </div>
      `;
    } else {
      modalHtml += `
        <div style="margin-bottom:12px;font-size:0.85rem;color:var(--text-muted);">
          数据库中暂无同名人员，请填写地址创建新人员
        </div>
      `;
    }

    // 显示每条记录
    modalHtml += `<div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:8px;">各条记录（填写地址区分）：</div>`;
    group.rows.forEach((row, rIdx) => {
      modalHtml += `
        <div class="record-row" data-row-idx="${row.row_idx}" data-group-idx="${gIdx}"
          style="display:flex;align-items:center;gap:12px;padding:8px;background:var(--bg);border-radius:4px;margin-bottom:8px;">
          <div style="min-width:100px;">
            <span style="color:var(--text-secondary);font-size:0.85rem;">${row.date || '-'}</span>
          </div>
          <div style="min-width:80px;">
            <span style="font-weight:600;">¥${(row.amount || 0).toLocaleString()}</span>
          </div>
          <div style="flex:1;">
            <input type="text" class="address-input" data-row-idx="${row.row_idx}"
              value="${row.address || ''}" placeholder="地址（相同=同一人）"
              style="width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:4px;font-size:0.85rem;">
          </div>
          <div style="min-width:60px;font-size:0.85rem;color:var(--text-secondary);">
            <span class="selected-person-label" data-row-idx="${row.row_idx}">-</span>
            <input type="hidden" class="selected-person-id" data-row-idx="${row.row_idx}" value="">
          </div>
        </div>
      `;
    });

    modalHtml += `</div>`;
  });

  modalHtml += `
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" onclick="cancelAddressConfirm()">取消</button>
          <button class="btn btn-primary" onclick="confirmAddresses()">确认并继续</button>
        </div>
      </div>
    </div>
  `;

  // 保存同名记录数据供后续使用
  window._sameNameRecords = sameNameRecords;

  // 添加到页面
  const existing = document.getElementById('address-confirm-modal');
  if (existing) existing.remove();
  document.body.insertAdjacentHTML('beforeend', modalHtml);

  // 绑定已有人员按钮点击事件
  document.querySelectorAll('.existing-person-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      const gIdx = parseInt(this.dataset.groupIdx);
      const personId = this.dataset.personId;
      const personName = this.querySelector('div:first-child').textContent;

      // 选中当前按钮
      this.parentElement.querySelectorAll('.existing-person-btn').forEach(b => b.style.borderColor = 'var(--border)');
      this.style.borderColor = 'var(--primary)';

      // 将该组所有记录关联到这个人员
      document.querySelectorAll(`.record-row[data-group-idx="${gIdx}"]`).forEach(row => {
        const rowIdx = row.dataset.rowIdx;
        row.querySelector('.selected-person-id').value = personId;
        row.querySelector('.selected-person-label').textContent = `已选`;
        row.querySelector('.selected-person-label').style.color = 'var(--primary)';
        // 清空地址输入
        row.querySelector('.address-input').value = '';
      });
    });
  });
}

function cancelAddressConfirm() {
  const modal = document.getElementById('address-confirm-modal');
  if (modal) modal.remove();
  document.getElementById('excel-file-input').value = '';
  document.getElementById('excel-file-name').textContent = '';
  window._importFileData = null;
  window._sameNameRecords = null;
}

async function confirmAddresses() {
  // 收集用户的选择：person_id 或 address
  const selections = [];
  document.querySelectorAll('.record-row').forEach(row => {
    const rowIdx = parseInt(row.dataset.rowIdx);
    if (isNaN(rowIdx) || rowIdx <= 0) return;

    const personIdInput = row.querySelector('.selected-person-id');
    const addressInput = row.querySelector('.address-input');

    const personId = personIdInput ? parseInt(personIdInput.value) : null;
    const address = addressInput ? (addressInput.value || '').trim() : '';

    selections.push({
      row_idx: rowIdx,
      person_id: personId && !isNaN(personId) ? personId : null,
      address: address
    });
  });

  if (selections.length === 0) {
    showToast('没有有效的记录', 'error');
    return;
  }

  showImportLoading('正在处理...');

  try {
    // 调用新API继续导入
    const res = await api(API + '/api/import/excel-with-address', {
      method: 'POST',
      body: JSON.stringify({
        file_data: window._importFileData,
        selections: selections
      })
    });

    hideImportLoading();

    if (!res) return;

    const data = await res.json();

    // 关闭弹窗
    const modal = document.getElementById('address-confirm-modal');
    if (modal) modal.remove();

    // 继续正常流程
    pendingExcelData = data.data;
    let countText = `共 ${data.total} 条 | 需确认 ${data.needs_confirm} 条 | 新人 ${data.new_persons} 条`;
    document.getElementById('excel-preview-count').textContent = countText;
    document.getElementById('excel-preview-area').style.display = 'block';
    renderExcelPreview(pendingExcelData);

    // 清理
    window._importFileData = null;
    window._sameNameRecords = null;
  } catch (e) {
    hideImportLoading();
    console.error('导入错误:', e);
    showToast('导入失败: ' + e.message, 'error');
  }
}

// 在指定索引处插入空白记录
function insertEmptyRecord(idx, position) {
  const emptyRecord = {
    row_idx: pendingExcelData.length + 1,
    date: new Date().toISOString().slice(0, 10),
    original_name: '',
    name: '',
    amount: 0,
    category: '其他',
    direction: 'income',
    address: '',
    note: '',
    auto_fixed: false,
    same_name_people: [],
    needs_confirm: false,
    selected_person_id: null,
    new_person_address: '',
    isEmpty: true  // 标记为空白记录
  };

  if (position === 'above') {
    pendingExcelData.splice(idx, 0, emptyRecord);
  } else if (position === 'below') {
    pendingExcelData.splice(idx + 1, 0, emptyRecord);
  }

  // 重新渲染
  renderExcelPreview(pendingExcelData);
  showToast('已添加空白记录');
}

function renderExcelPreview(data) {
  // 排序：需要确认的记录置顶，自动匹配的其次，新人员最后
  pendingExcelData = [...data].sort((a, b) => {
    if (a.needs_confirm && !b.needs_confirm) return -1;
    if (!a.needs_confirm && b.needs_confirm) return 1;
    if (a.auto_fixed && !b.auto_fixed) return -1;
    if (!a.auto_fixed && b.auto_fixed) return 1;
    return 0;
  });

  if (isMobile) {
    // 移动端：渲染卡片列表
    renderMobilePreview(pendingExcelData);
  } else {
    // Web端：渲染表格
    renderDesktopPreview(pendingExcelData);
  }
}

function renderMobilePreview(data) {
  const container = document.getElementById('excel-preview-mobile');
  container.innerHTML = '';
  container.style.display = 'block';

  if (data.length === 0) {
    container.innerHTML = '<div class="empty-state"><div class="icon">📋</div><p>暂无记录</p></div>';
    return;
  }

  data.forEach((item, idx) => {
    let borderColor = '#22c55e';
    let statusIcon = '✓';
    if (item.needs_confirm) {
      borderColor = '#f59e0b';
      statusIcon = '⚠️';
    } else if (item.auto_fixed) {
      borderColor = '#22c55e';
      statusIcon = '✓';
    } else if (item.selected_person_id) {
      borderColor = '#6366f1';
      statusIcon = '✓';
    }

    const card = el('div', {
      className: 'mobile-preview-card',
      style: {
        background: 'var(--bg-card)',
        borderRadius: '12px',
        padding: '16px',
        marginBottom: '12px',
        boxShadow: 'var(--shadow)',
        borderLeft: `4px solid ${borderColor}`
      }
    });

    // 头部：姓名和金额
    const header = el('div', {
      style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }
    },
      el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px' } },
        el('input', {
          type: 'checkbox',
          checked: true,
          className: 'excel-row-check',
          dataset: { idx: idx },
          style: { width: '20px', height: '20px' }
        }),
        el('input', {
          type: 'text',
          value: item.name || '',
          placeholder: '姓名',
          style: { fontSize: '16px', fontWeight: '700', border: 'none', background: 'transparent', outline: 'none', width: '120px' },
          oninput: function() { item.name = this.value; },
          onblur: function() { rematchPerson(idx); }
        })
      ),
      el('div', { style: { display: 'flex', alignItems: 'center', gap: '4px' } },
        el('span', { style: { fontSize: '12px', color: borderColor } }, statusIcon),
        el('input', {
          type: 'number',
          value: item.amount || 0,
          placeholder: '金额',
          style: { fontSize: '18px', fontWeight: '700', border: 'none', background: 'transparent', outline: 'none', width: '80px', textAlign: 'right', color: item.direction === 'income' ? 'var(--income)' : 'var(--expense)' },
          oninput: function() { item.amount = parseFloat(this.value) || 0; }
        })
      )
    );
    card.appendChild(header);

    // 详情行
    const details = el('div', {
      style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '14px' }
    },
      el('div', null,
        el('label', { style: { color: 'var(--text-muted)', fontSize: '12px' } }, '日期'),
        el('input', {
          type: 'date',
          value: item.date || '',
          style: { width: '100%', padding: '8px', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '14px' },
          oninput: function() { item.date = this.value; }
        })
      ),
      el('div', null,
        el('label', { style: { color: 'var(--text-muted)', fontSize: '12px' } }, '分类'),
        el('select', {
          style: { width: '100%', padding: '8px', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '14px' },
          onchange: function() { item.category = this.value; }
        }, ...['婚嫁', '葬礼', '生日', '乔迁', '开业', '其他'].map(c =>
          el('option', { value: c, selected: item.category === c }, c)
        ))
      ),
      el('div', null,
        el('label', { style: { color: 'var(--text-muted)', fontSize: '12px' } }, '方向'),
        el('select', {
          style: { width: '100%', padding: '8px', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '14px' },
          onchange: function() { item.direction = this.value; }
        },
          el('option', { value: 'income', selected: item.direction === 'income' }, '收礼'),
          el('option', { value: 'expense', selected: item.direction === 'expense' }, '送礼')
        )
      ),
      el('div', null,
        el('label', { style: { color: 'var(--text-muted)', fontSize: '12px' } }, '备注'),
        el('input', {
          type: 'text',
          value: item.note || '',
          placeholder: '备注',
          style: { width: '100%', padding: '8px', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '14px' },
          oninput: function() { item.note = this.value; }
        })
      )
    );
    card.appendChild(details);

    // 操作按钮
    const actions = el('div', {
      style: { display: 'flex', gap: '8px', marginTop: '12px' }
    },
      el('button', {
        className: 'btn btn-secondary',
        style: { flex: 1, padding: '8px', fontSize: '12px' },
        onclick: () => { insertEmptyRecord(idx, 'above'); }
      }, '↑ 上方插入'),
      el('button', {
        className: 'btn btn-secondary',
        style: { flex: 1, padding: '8px', fontSize: '12px' },
        onclick: () => { insertEmptyRecord(idx, 'below'); }
      }, '↓ 下方插入')
    );
    card.appendChild(actions);

    // 人员关联提示
    if (item.needs_confirm && item.same_name_people && item.same_name_people.length > 0) {
      const personHint = el('div', {
        style: { marginTop: '12px', padding: '12px', background: '#fffbeb', borderRadius: '8px', fontSize: '13px' }
      },
        el('div', { style: { fontWeight: '600', color: '#f59e0b', marginBottom: '8px' } }, '⚠️ 需要选择关联人员'),
        ...item.same_name_people.map((p, pi) =>
          el('label', {
            style: { display: 'flex', alignItems: 'center', gap: '8px', padding: '8px', cursor: 'pointer' }
          },
            el('input', {
              type: 'radio',
              name: `mobile-person-${idx}`,
              value: p.id,
              style: { width: '16px', height: '16px' },
              onchange: function() { item.selected_person_id = p.id; }
            }),
            el('span', null, `${p.name} ${p.address ? `(${p.address})` : ''}`)
          )
        ),
        el('label', {
          style: { display: 'flex', alignItems: 'center', gap: '8px', padding: '8px', cursor: 'pointer' }
        },
          el('input', {
            type: 'radio',
            name: `mobile-person-${idx}`,
            value: 'new',
            style: { width: '16px', height: '16px' },
            onchange: function() {
              item.selected_person_id = null;
              const addrInput = card.querySelector('.new-addr-input');
              if (addrInput) addrInput.style.display = 'block';
            }
          }),
          el('span', null, '创建新人员')
        ),
        el('input', {
          type: 'text',
          placeholder: '输入地址区分同名人员',
          className: 'new-addr-input',
          style: { display: 'none', width: '100%', padding: '8px', marginTop: '8px', border: '1px solid var(--border)', borderRadius: '6px' },
          oninput: function() { item.new_person_address = this.value; item.address = this.value; }
        })
      );
      card.appendChild(personHint);
    }

    container.appendChild(card);
  });
}

function renderDesktopPreview(data) {
  const tbody = document.getElementById('excel-preview-body');
  tbody.innerHTML = '';

  pendingExcelData.forEach((item, idx) => {
    // 根据状态设置行背景色
    const tr = el('tr');
    if (item.needs_confirm) {
      tr.style.background = '#fffbeb';  // 需要确认 - 浅橙色背景
    } else if (item.auto_fixed) {
      tr.style.background = '#f0fdf4';  // 自动匹配 - 浅绿色背景
    }

    // Checkbox
    const cb = el('input', { type: 'checkbox', checked: true, className: 'excel-row-check' });
    cb.dataset.idx = idx;
    tr.appendChild(cb);

    // Date - 可编辑
    const dateInput = el('input', {
      type: 'date',
      value: item.date || '',
      style: { width: '130px', padding: '4px 6px', border: '1px solid var(--border)', borderRadius: '4px', fontSize: '0.85rem' },
      oninput: function() { item.date = this.value; }
    });
    tr.appendChild(el('td', null, dateInput));

    // Name - 可编辑，根据状态显示不同颜色
    const nameTd = el('td');
    let nameBorderColor = '#22c55e';  // 默认绿色边框（新人员）
    let statusIcon = '';
    if (item.needs_confirm) {
      nameBorderColor = '#f59e0b';  // 需要确认 - 橙色
      statusIcon = '⚠️ ';
    } else if (item.auto_fixed) {
      nameBorderColor = '#22c55e';  // 自动匹配 - 绿色
      statusIcon = '✓ ';
    } else if (item.selected_person_id) {
      nameBorderColor = '#6366f1';  // 已关联 - 蓝色
      statusIcon = '✓ ';
    }
    const nameInput = el('input', {
      type: 'text',
      value: item.name || '',
      style: { width: '100px', padding: '4px 6px', border: `2px solid ${nameBorderColor}`, borderRadius: '4px', fontSize: '0.85rem', fontWeight: '600' },
      oninput: function() { item.name = this.value; },
      onblur: function() { rematchPerson(idx); }
    });
    nameTd.appendChild(el('span', {}, statusIcon));
    nameTd.appendChild(nameInput);
    tr.appendChild(nameTd);

    // Amount - 可编辑
    const amountInput = el('input', {
      type: 'number',
      value: item.amount || 0,
      step: '0.01',
      min: '0',
      style: { width: '90px', padding: '4px 6px', border: '1px solid var(--border)', borderRadius: '4px', fontSize: '0.85rem', textAlign: 'right' },
      oninput: function() { item.amount = parseFloat(this.value) || 0; }
    });
    tr.appendChild(el('td', { style: { whiteSpace: 'nowrap' } }, amountInput));

    // Category - 可编辑下拉选择
    const categorySelect = el('select', {
      style: { padding: '4px 6px', border: '1px solid var(--border)', borderRadius: '4px', fontSize: '0.85rem' },
      onchange: function() { item.category = this.value; }
    });
    const categories = ['婚嫁', '葬礼', '生日', '乔迁', '开业', '其他'];
    categories.forEach(cat => {
      const opt = el('option', { value: cat }, cat);
      if (item.category === cat) opt.selected = true;
      categorySelect.appendChild(opt);
    });
    tr.appendChild(el('td', null, categorySelect));

    // Direction - 可编辑下拉选择
    const dirSelect = el('select', {
      style: { padding: '4px 6px', border: '1px solid var(--border)', borderRadius: '4px', fontSize: '0.85rem' },
      onchange: function() { item.direction = this.value; }
    });
    const dirIncome = el('option', { value: 'income' }, '收礼');
    const dirExpense = el('option', { value: 'expense' }, '送礼');
    if (item.direction === 'income') dirIncome.selected = true;
    else dirExpense.selected = true;
    dirSelect.appendChild(dirIncome);
    dirSelect.appendChild(dirExpense);
    tr.appendChild(el('td', null, dirSelect));

    // Note - 可编辑
    const noteInput = el('input', {
      type: 'text',
      value: item.note || '',
      placeholder: '备注',
      style: { width: '100px', padding: '4px 6px', border: '1px solid var(--border)', borderRadius: '4px', fontSize: '0.85rem' },
      oninput: function() { item.note = this.value; }
    });
    tr.appendChild(el('td', { style: { maxWidth: '120px' } }, noteInput));

    // 操作列 - 添加空白记录按钮
    const actionTd = el('td', { style: { whiteSpace: 'nowrap' } });
    const btnAbove = el('button', {
      className: 'btn btn-sm btn-secondary',
      style: { padding: '2px 6px', fontSize: '0.75rem', marginRight: '4px' },
      onclick: function() { insertEmptyRecord(idx, 'above'); },
      title: '在当前行上方插入空白记录'
    }, '↑ 插入');
    const btnBelow = el('button', {
      className: 'btn btn-sm btn-secondary',
      style: { padding: '2px 6px', fontSize: '0.75rem' },
      onclick: function() { insertEmptyRecord(idx, 'below'); },
      title: '在当前行下方插入空白记录'
    }, '↓ 插入');
    actionTd.appendChild(btnAbove);
    actionTd.appendChild(btnBelow);
    tr.appendChild(actionTd);

    // Person selection - 使用统一渲染函数
    const tdPerson = el('td', { style: { minWidth: '200px' } });
    renderPersonCell(item, idx, tdPerson);

    tr.appendChild(tdPerson);
    tbody.appendChild(tr);
  });
}

// 重新匹配人员
async function rematchPerson(idx) {
  const item = pendingExcelData[idx];
  if (!item) return;

  const name = item.name?.trim();
  if (!name) return;

  try {
    const res = await api(API + '/api/import/match-person', {
      method: 'POST',
      body: JSON.stringify({ name })  // 只用姓名匹配
    });

    if (!res || !res.ok) return;

    const data = await res.json();

    // 更新item数据
    item.same_name_people = data.same_name_people || [];
    item.needs_confirm = data.needs_confirm;
    item.selected_person_id = data.selected_person_id;
    item.auto_fixed = data.auto_fixed;
    item.new_person_address = '';

    // 重新渲染该行的人员关联部分
    const row = document.querySelectorAll('#excel-preview-body tr')[idx];
    if (row) {
      const tdPerson = row.querySelector('td:last-child');
      const nameInput = row.querySelectorAll('td')[2]?.querySelector('input');

      // 更新姓名输入框边框颜色
      if (nameInput) {
        let borderColor = '#22c55e';
        if (item.needs_confirm) borderColor = '#f59e0b';
        else if (item.auto_fixed) borderColor = '#22c55e';
        else if (item.selected_person_id) borderColor = '#6366f1';
        nameInput.style.border = `2px solid ${borderColor}`;
      }

      // 重新渲染人员关联区域
      tdPerson.innerHTML = '';
      renderPersonCell(item, idx, tdPerson);

      // 更新行背景色
      if (item.needs_confirm) {
        row.style.background = '#fffbeb';
      } else if (item.auto_fixed) {
        row.style.background = '#f0fdf4';
      } else {
        row.style.background = '';
      }
    }
  } catch (e) {
    console.error('匹配人员失败:', e);
  }
}

// 渲染人员关联单元格
function renderPersonCell(item, idx, tdPerson) {
  if (item.selected_person_id && !item.needs_confirm) {
    const linkedDiv = el('div', { style: { padding: '8px', background: 'var(--bg-secondary)', borderRadius: '4px' } });
    if (item.auto_fixed) {
      linkedDiv.innerHTML = `<span style="color:#22c55e;font-weight:600;">✓ 自动匹配</span>`;
    } else {
      linkedDiv.innerHTML = `<span style="color:var(--primary);font-weight:600;">✓ 已关联</span>`;
    }
    tdPerson.appendChild(linkedDiv);
  }
  else if (item.needs_confirm && item.same_name_people && item.same_name_people.length > 0) {
    const card = el('div', { className: 'person-confirm-card', 'data-idx': idx, style: { border: '2px solid #f59e0b', borderRadius: '8px', padding: '12px', background: '#fffbeb' } });

    const hint = el('div', { style: { fontSize: '0.85rem', color: '#f59e0b', fontWeight: '600', marginBottom: '8px' } }, '⚠️ 请选择关联人员：');
    card.appendChild(hint);

    item.same_name_people.forEach((p, pIdx) => {
      const radioId = `person-${idx}-${pIdx}`;
      const radioLabel = el('label', { className: 'person-option', style: { display: 'flex', alignItems: 'center', marginBottom: '6px', cursor: 'pointer' } });

      const radio = el('input', { type: 'radio', name: `person-select-${idx}`, value: p.id, id: radioId });
      radio.addEventListener('change', function() {
        item.selected_person_id = p.id;
        item.new_person_address = '';
        const addrInput = card.querySelector('.new-person-address-input');
        if (addrInput) addrInput.value = '';
        const newPersonSection = card.querySelector('.new-person-section');
        if (newPersonSection) newPersonSection.style.display = 'none';
      });
      radioLabel.appendChild(radio);

      const infoSpan = el('span', { style: { marginLeft: '8px', fontSize: '0.85rem' } });
      const addrText = p.address ? `（${p.address}）` : '';
      const balanceText = p.balance >= 0 ? `+¥${p.balance}` : `-¥${Math.abs(p.balance)}`;
      infoSpan.innerHTML = `<strong>${p.name}</strong>${addrText} — 往来${p.tx_count}笔，余额${balanceText}`;
      radioLabel.appendChild(infoSpan);
      card.appendChild(radioLabel);
    });

    const newRadioId = `person-${idx}-new`;
    const newRadioLabel = el('label', { className: 'person-option', style: { display: 'flex', alignItems: 'center', marginBottom: '6px', cursor: 'pointer' } });
    const newRadio = el('input', { type: 'radio', name: `person-select-${idx}`, value: '__new__', id: newRadioId });
    newRadio.addEventListener('change', function() {
      item.selected_person_id = null;
      const newPersonSection = card.querySelector('.new-person-section');
      if (newPersonSection) newPersonSection.style.display = 'block';
    });
    newRadioLabel.appendChild(newRadio);
    newRadioLabel.appendChild(el('span', { style: { marginLeft: '8px', fontSize: '0.85rem' } }, '以上都不是，创建新人员'));
    card.appendChild(newRadioLabel);

    const newPersonSection = el('div', { className: 'new-person-section', style: { display: 'none', marginTop: '8px', paddingLeft: '24px' } });
    const addrInput = el('input', {
      type: 'text',
      className: 'new-person-address-input',
      placeholder: '填写地址（用于区分同名人员）',
      style: { width: '100%', padding: '6px 8px', border: '1px solid var(--border)', borderRadius: '4px', fontSize: '0.85rem' },
      onblur: function() { item.address = this.value; rematchPerson(idx); }
    });
    addrInput.addEventListener('input', function() {
      item.new_person_address = this.value;
    });
    newPersonSection.appendChild(addrInput);
    card.appendChild(newPersonSection);

    tdPerson.appendChild(card);
  } else {
    const fields = el('div', { className: 'excel-new-person-fields', 'data-idx': idx, style: { marginTop: '4px' } });
    fields.innerHTML = `<div style="font-size:0.85rem;color:var(--text-secondary);marginBottom:4px;">新人员，填写地址：</div>
      <input class="new-person-address-input" placeholder="地址（如：北京市朝阳区）" style="width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:4px;" value="${item.new_person_address||item.address||''}">`;
    tdPerson.appendChild(fields);

    const addrInput = fields.querySelector('.new-person-address-input');
    if (addrInput) {
      addrInput.addEventListener('input', function() {
        item.new_person_address = this.value;
        item.address = this.value;
      });
      addrInput.addEventListener('blur', function() {
        item.address = this.value;
        rematchPerson(idx);
      });
    }
  }
}

function cancelImport() {
  document.getElementById('excel-preview-area').style.display = 'none';
  document.getElementById('excel-file-input').value = '';
  document.getElementById('excel-file-name').textContent = '';
  pendingExcelData = null;

  // 清空照片识别相关数据
  _photoResults = [];
  _currentPhotoIndex = 0;
  _totalPhotos = 0;
  _recognizingIndex = 0;

  // 移除图片切换器
  const switcher = document.getElementById('photo-switcher');
  if (switcher) switcher.remove();
}

function toggleExcelSelectAll() {
  const checked = document.getElementById('excel-select-all').checked;
  document.querySelectorAll('#excel-preview-body .excel-row-check').forEach(cb => cb.checked = checked);
}


/* ── Change Password ── */
async function changePassword() {
  const oldPwd = document.getElementById('pwd-old').value;
  const newPwd = document.getElementById('pwd-new').value;
  const newPwd2 = document.getElementById('pwd-new2').value;
  if (newPwd !== newPwd2) { showToast('两次新密码不一致', 'error'); return; }
  if (newPwd.length < 6) { showToast('新密码至少6位', 'error'); return; }
  const res = await api(API + '/api/auth/password', {
    method: 'PUT',
    body: JSON.stringify({ old_password: oldPwd, new_password: newPwd }),
  });
  if (!res) return;
  if (res.ok) {
    showToast('密码修改成功');
    document.getElementById('pwd-modal').classList.remove('show');
    document.getElementById('pwd-old').value = '';
    document.getElementById('pwd-new').value = '';
    document.getElementById('pwd-new2').value = '';
  }
}

/* ── Tab Navigation ── */
function showTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.style.display = 'none');
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).style.display = 'block';
  event.target.classList.add('active');
  if (name === 'summary') loadSummary();
  if (name === 'people') loadPersonList();
  if (name === 'list') loadCategories();
}

function toggleUserMenu() {
  const dd = document.getElementById('user-dropdown');
  dd.style.display = dd.style.display === 'block' ? 'none' : 'block';
}

function showChangePassword() {
  document.getElementById('pwd-modal').classList.add('show');
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', () => {
  if (token) {
    api(API + '/api/auth/me').then(res => {
      if (!res) return;
      res.json().then(data => {
        currentUser = data;
        localStorage.setItem('gift_user', JSON.stringify(data));
        enterApp();
      });
    });
  }
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const res = await api(API + '/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    });
    if (!res) return;
    if (res.ok) {
      const data = await res.json();
      token = data.token;
      currentUser = data.user;
      localStorage.setItem('gift_token', token);
      localStorage.setItem('gift_user', JSON.stringify(data.user));
      showToast('登录成功');
      enterApp();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || '登录失败', 'error');
    }
  });

  document.getElementById('register-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('reg-username').value.trim();
    const displayName = document.getElementById('reg-display-name').value.trim();
    const password = document.getElementById('reg-password').value;
    const password2 = document.getElementById('reg-password2').value;
    if (password !== password2) { showToast('两次密码不一致', 'error'); return; }
    const res = await api(API + '/api/auth/register', {
      method: 'POST', body: JSON.stringify({ username, password, display_name: displayName }),
    });
    if (!res) return;
    if (res.ok) { showToast('注册成功，请登录'); switchLoginTab('login'); }
    else { const err = await res.json().catch(() => ({})); showToast(err.detail || '注册失败', 'error'); }
  });

  document.getElementById('tx-form').addEventListener('submit', addTransaction);
  document.getElementById('cat-form').addEventListener('submit', addCategory);

  const dateInput = document.querySelector('[name="date"]');
  if (dateInput) dateInput.value = new Date().toISOString().slice(0, 10);
});

/* ── Person Edit & Delete ── */
let _editingPersonId = null;

async function editPerson(id) {
  _editingPersonId = id;
  const res = await api(API + '/api/people/' + id);
  if (!res) return;
  const person = await res.json();

  document.getElementById('drawer-person-name').value = person.name || '';
  document.getElementById('drawer-person-phone').value = person.phone || '';
  document.getElementById('drawer-person-address').value = person.address || '';
  document.getElementById('drawer-person-note').value = person.note || '';
  document.querySelector('#add-person-drawer .drawer-header h3').textContent = '编辑人员';
  document.querySelector('#add-person-drawer .drawer-footer .btn-primary').textContent = '保存';
  openDrawer('add-person-drawer');
}

async function submitAddPerson() {
  const name = document.getElementById('drawer-person-name').value.trim();
  if (!name) {
    showToast('请输入人名', 'error');
    return;
  }

  const phone = document.getElementById('drawer-person-phone').value.trim();
  const address = document.getElementById('drawer-person-address').value.trim();
  const note = document.getElementById('drawer-person-note').value.trim();

  let res;
  if (_editingPersonId) {
    // 编辑模式
    res = await api(API + '/api/people/' + _editingPersonId, {
      method: 'PUT',
      body: JSON.stringify({ name, phone, address, note })
    });
  } else {
    // 新增模式
    res = await api(API + '/api/people', {
      method: 'POST',
      body: JSON.stringify({ name, phone, address, note })
    });
  }

  if (!res) return;

  if (res.ok || res.status === 200 || res.status === 201) {
    const data = await res.json();
    showToast(data.message || (_editingPersonId ? '人员更新成功' : '人员创建成功'));
    // 先保存回调引用，再关闭抽屉
    const callback = _personCallback;
    closeDrawer('add-person-drawer');
    // 执行回调
    if (callback) {
      callback({ id: data.id || _editingPersonId, name });
    }
    // 刷新人员列表
    loadPersonList();
  } else {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || '操作失败', 'error');
  }
}

function openDrawer(id) {
  document.getElementById(id).classList.add('show');
}

function closeDrawer(id) {
  document.getElementById(id).classList.remove('show');
  // 清除回调，防止意外执行
  _personCallback = null;
  // 重置编辑状态
  if (id === 'add-person-drawer') {
    _editingPersonId = null;
    document.querySelector('#add-person-drawer .drawer-header h3').textContent = '新增人员';
    document.querySelector('#add-person-drawer .drawer-footer .btn-primary').textContent = '保存';
  }
}

async function confirmDeletePerson(id, name, cnt) {
  const modal = document.getElementById('delete-person-modal');
  const body = document.getElementById('delete-person-modal-body');

  let html = `<p>确定要删除人员 <strong>${name}</strong> 吗？</p>`;

  if (cnt > 0) {
    html += `<p style="color:var(--expense);margin-top:8px;">该人员有 ${cnt} 条关联记录，删除后这些记录的人员关联将被清除。</p>`;
    html += `<div style="margin-top:12px;max-height:200px;overflow-y:auto;">`;
    html += `<button class="btn btn-sm btn-secondary" onclick="loadPersonTransactions(${id})">查看关联记录</button>`;
    html += `<div id="delete-person-transactions" style="margin-top:8px;"></div>`;
    html += `</div>`;
  }

  body.innerHTML = html;
  document.getElementById('delete-person-confirm-btn').onclick = () => deletePerson(id);
  modal.classList.add('show');
}

async function loadPersonTransactions(personId) {
  const container = document.getElementById('delete-person-transactions');
  container.innerHTML = '<p style="color:var(--text-muted);">加载中...</p>';

  const res = await api(API + '/api/transactions?person_id=' + personId + '&size=50');
  if (!res) return;

  const data = await res.json();
  const txs = data.data || [];

  if (txs.length === 0) {
    container.innerHTML = '<p style="color:var(--text-muted);">无关联记录</p>';
    return;
  }

  container.innerHTML = `<table style="width:100%;font-size:12px;">
    <thead><tr><th>日期</th><th>金额</th><th>分类</th><th>方向</th></tr></thead>
    <tbody>${txs.map(t => `<tr>
      <td>${t.date}</td>
      <td class="${t.direction==='income'?'amount-income':'amount-expense'}">${t.direction==='income'?'+':'-'}${fmt(Number(t.amount)||0)}</td>
      <td>${t.category}</td>
      <td>${t.direction==='income'?'收礼':'送礼'}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

async function deletePerson(id) {
  const res = await api(API + '/api/people/' + id, { method: 'DELETE' });
  if (!res) return;

  if (res.ok) {
    showToast('人员删除成功');
    document.getElementById('delete-person-modal').classList.remove('show');
    loadPersonList();
  } else {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || '删除失败', 'error');
  }
}

/* ─────────────────────────────────────────────────────────
   📷 拍照识别导入功能
   ───────────────────────────────────────────────────────── */

// 照片数据存储
let _selectedPhotos = [];  // Base64图片数组
let _cameraStream = null;  // 相机流

// 切换导入模式
function switchImportMode(mode) {
  document.querySelectorAll('.import-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + mode).classList.add('active');

  document.getElementById('import-excel-area').style.display = mode === 'excel' ? 'block' : 'none';
  document.getElementById('import-photo-area').style.display = mode === 'photo' ? 'block' : 'none';

  // 隐藏预览区
  document.getElementById('excel-preview-area').style.display = 'none';

  // 切换模式时关闭相机
  if (mode === 'excel' && _cameraStream) {
    closeCamera();
  }

  // 初始化分类下拉框
  if (mode === 'photo') {
    initPhotoCategorySelect();
  }
}

// 初始化照片分类下拉框
function initPhotoCategorySelect() {
  const select = document.getElementById('photo-category');
  if (select && select.options.length <= 1) {
    api(API + '/api/categories').then(res => {
      if (!res) return;
      return res.json();
    }).then(cats => {
      if (!cats) return;
      select.innerHTML = '<option value="">AI自动判断</option>' +
        cats.map(c => `<option value="${c.name}">${c.name}</option>`).join('');
    });
  }
}

// 打开相机
async function openCamera() {
  try {
    const constraints = {
      video: {
        facingMode: 'environment',  // 后置摄像头
        width: { ideal: 1920 },
        height: { ideal: 1080 }
      }
    };

    _cameraStream = await navigator.mediaDevices.getUserMedia(constraints);
    const video = document.getElementById('camera-preview');
    video.srcObject = _cameraStream;
    video.style.display = 'block';
    document.getElementById('camera-controls').style.display = 'flex';

    showToast('相机已打开，请对准礼簿拍照');
  } catch (err) {
    console.error('打开相机失败:', err);
    showToast('无法访问相机，请检查权限或使用相册选择', 'error');
  }
}

// 关闭相机
function closeCamera() {
  if (_cameraStream) {
    _cameraStream.getTracks().forEach(track => track.stop());
    _cameraStream = null;
  }
  document.getElementById('camera-preview').style.display = 'none';
  document.getElementById('camera-controls').style.display = 'none';
}

// 拍照
function capturePhoto() {
  const video = document.getElementById('camera-preview');
  const canvas = document.getElementById('camera-canvas');

  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;

  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0);

  // 压缩并转为base64
  const quality = 0.8;
  const base64 = canvas.toDataURL('image/jpeg', quality);

  addPhoto(base64);
  showToast('已拍摄照片，可继续拍摄或点击识别');
}

// 处理文件选择
function handlePhotoSelect(input) {
  const files = input.files;
  if (!files || files.length === 0) return;

  Array.from(files).forEach(file => {
    if (!file.type.startsWith('image/')) {
      showToast(`${file.name} 不是有效图片`, 'error');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      // 压缩图片
      compressImage(e.target.result, (compressed) => {
        addPhoto(compressed);
      });
    };
    reader.readAsDataURL(file);
  });

  // 清空input，允许重复选择同一文件
  input.value = '';
}

// 压缩图片
function compressImage(dataUrl, callback, maxWidth = 1280, quality = 0.6) {
  const img = new Image();
  img.onload = () => {
    let width = img.width;
    let height = img.height;

    if (width > maxWidth) {
      height = (height * maxWidth) / width;
      width = maxWidth;
    }

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, width, height);

    callback(canvas.toDataURL('image/jpeg', quality));
  };
  img.src = dataUrl;
}

// 添加照片到列表
function addPhoto(base64) {
  _selectedPhotos.push(base64);
  updatePhotoPreviewGrid();
}

// 更新照片预览网格
function updatePhotoPreviewGrid() {
  const grid = document.getElementById('photo-preview-grid');
  grid.innerHTML = _selectedPhotos.map((photo, idx) => `
    <div class="photo-preview-item" style="position:relative;width:100px;height:100px;">
      <img src="${photo}" style="width:100%;height:100%;object-fit:cover;border-radius:8px;">
      <button onclick="removePhoto(${idx})" style="position:absolute;top:-8px;right:-8px;width:24px;height:24px;border-radius:50%;background:var(--expense);color:white;border:none;cursor:pointer;font-size:14px;">×</button>
      <div style="position:absolute;bottom:4px;left:4px;background:rgba(0,0,0,0.6);color:white;font-size:12px;padding:2px 6px;border-radius:4px;">${idx + 1}</div>
    </div>
  `).join('');
}

// 删除照片
function removePhoto(idx) {
  _selectedPhotos.splice(idx, 1);
  updatePhotoPreviewGrid();
}

// 提交照片识别
let _photoResults = [];  // 每张图片的识别结果
let _currentPhotoIndex = 0;  // 当前显示的图片索引
let _totalPhotos = 0;  // 总图片数
let _recognizingIndex = 0;  // 正在识别的图片索引

async function submitPhotoRecognition() {
  if (_selectedPhotos.length === 0) {
    showToast('请先选择或拍摄照片', 'error');
    return;
  }

  // 获取用户输入
  const date = document.getElementById('photo-date').value || null;
  const category = document.getElementById('photo-category').value || null;
  const note = document.getElementById('photo-note').value.trim() || null;
  const userPrompt = document.getElementById('photo-prompt')?.value.trim().slice(0, 500) || null;

  // 显示加载状态
  const btn = document.getElementById('btn-photo-submit');
  const originalText = btn.textContent;
  btn.textContent = '📤 上传图片中...';
  btn.disabled = true;

  // 初始化状态
  _photoResults = [];
  _totalPhotos = _selectedPhotos.length;
  _currentPhotoIndex = 0;
  _recognizingIndex = 0;

  showImportLoading('正在上传图片...');

  try {
    // 第一步：上传所有图片，获取URL
    const uploadedUrls = [];
    for (let i = 0; i < _selectedPhotos.length; i++) {
      showImportLoading(`上传图片 ${i + 1}/${_selectedPhotos.length}...`);

      const photo = _selectedPhotos[i];
      const response = await fetch(photo);
      const blob = await response.blob();

      const formData = new FormData();
      formData.append('file', blob, 'photo.jpg');

      const uploadRes = await fetch(API + '/api/import/photo-upload', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token },
        body: formData
      });

      if (!uploadRes.ok) {
        throw new Error('上传图片失败');
      }

      const uploadData = await uploadRes.json();
      uploadedUrls.push(uploadData.url);
    }

    // 初始化预览区
    document.getElementById('excel-preview-area').style.display = 'block';
    pendingExcelData = [];

    // 显示初始状态
    updatePhotoRecognitionUI();

    // 第二步：用URL调用识别API（流式）
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;

    const response = await fetch(API + '/api/import/photo-preview', {
      method: 'POST',
      headers,
      body: JSON.stringify({ image_urls: uploadedUrls, date, category, note, user_prompt: userPrompt })
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || '识别失败');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));

            if (data.done) {
              // 全部识别完成
              hideImportLoading();
              _recognizingIndex = _totalPhotos;
              updatePhotoRecognitionUI();
              showToast(`识别完成！共 ${_totalPhotos} 张图片，${_photoResults.reduce((a, b) => a + (b?.data?.length || 0), 0)} 条记录`);
            } else if (data.batch !== undefined) {
              // 单张图片识别完成
              _recognizingIndex = data.batch;
              _photoResults[data.batch - 1] = {
                index: data.batch,
                total: data.total_batches,
                data: data.data || [],
                error: data.error || null,
                accumulated: data.accumulated || {}
              };

              // 第一张识别完就解除锁定
              if (data.batch === 1) {
                hideImportLoading();
                _currentPhotoIndex = 0;
                showPhotoResult(0);
              }

              // 更新UI
              updatePhotoRecognitionUI();
            }
          } catch (e) {
            console.error('解析SSE数据失败:', e);
          }
        }
      }
    }

    // 清空照片
    _selectedPhotos = [];
    updatePhotoPreviewGrid();
    document.getElementById('photo-date').value = '';
    document.getElementById('photo-category').value = '';
    document.getElementById('photo-note').value = '';
    const photoPromptEl = document.getElementById('photo-prompt');
    if (photoPromptEl) photoPromptEl.value = '';

  } catch (err) {
    hideImportLoading();
    console.error('识别错误:', err);
    showToast('操作失败: ' + err.message, 'error');
  }

  btn.textContent = originalText;
  btn.disabled = false;
}

// 更新识别进度UI
function updatePhotoRecognitionUI() {
  const container = document.getElementById('excel-preview-count');
  const recognized = _photoResults.filter(r => r).length;

  if (_recognizingIndex < _totalPhotos) {
    container.innerHTML = `
      <span style="color:var(--primary);font-weight:600;">
        📷 识别进度: ${_recognizingIndex}/${_totalPhotos} 张
      </span>
      <span style="margin-left:12px;color:var(--text-secondary);">
        (识别完一张即可编辑)
      </span>
    `;
  } else {
    const totalRecords = _photoResults.reduce((a, b) => a + (b?.data?.length || 0), 0);
    container.innerHTML = `<span style="color:var(--income);font-weight:600;">✓ 识别完成: ${_totalPhotos} 张图片，${totalRecords} 条记录</span>`;
  }

  // 显示图片切换器
  renderPhotoSwitcher();
}

// 渲染图片切换器
function renderPhotoSwitcher() {
  let switcher = document.getElementById('photo-switcher');
  if (!switcher) {
    switcher = el('div', { id: 'photo-switcher', style: { display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' } });
    const previewArea = document.getElementById('excel-preview-area');
    previewArea.insertBefore(switcher, previewArea.querySelector('.table-wrapper') || previewArea.firstChild.nextSibling);
  }

  switcher.innerHTML = '';

  for (let i = 0; i < _totalPhotos; i++) {
    const result = _photoResults[i];
    const isCurrent = i === _currentPhotoIndex;
    const isRecognized = result && result.data;

    const btn = el('button', {
      className: `btn ${isCurrent ? 'btn-primary' : 'btn-secondary'}`,
      style: { padding: '8px 16px', position: 'relative' },
      onclick: () => showPhotoResult(i)
    });

    if (isRecognized) {
      btn.textContent = `📷 ${i + 1} (${result.data.length}条)`;
      if (result.error) {
        btn.style.borderColor = 'var(--expense)';
      }
    } else if (i < _recognizingIndex) {
      btn.textContent = `📷 ${i + 1} 识别中...`;
      btn.disabled = true;
    } else if (i === _recognizingIndex && _recognizingIndex < _totalPhotos) {
      btn.textContent = `📷 ${i + 1} 识别中...`;
      btn.disabled = true;
    } else {
      btn.textContent = `📷 ${i + 1} 等待中`;
      btn.disabled = true;
    }

    switcher.appendChild(btn);
  }
}

// 显示指定图片的识别结果
function showPhotoResult(index) {
  _currentPhotoIndex = index;
  const result = _photoResults[index];

  if (!result) {
    return;
  }

  // 更新切换器高亮
  renderPhotoSwitcher();

  // 渲染当前图片的数据
  if (result.data && result.data.length > 0) {
    pendingExcelData = result.data;
    renderExcelPreview(pendingExcelData);
  } else if (result.error) {
    document.getElementById('excel-preview-body').innerHTML = `
      <tr><td colspan="9" style="text-align:center;color:var(--expense);padding:32px;">
        ❌ 识别失败: ${result.error}
      </td></tr>
    `;
  } else {
    document.getElementById('excel-preview-body').innerHTML = `
      <tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:32px;">
        该图片未识别出有效记录
      </td></tr>
    `;
  }
}

// 确认导入当前图片的数据
async function confirmImport() {
  const checks = document.querySelectorAll('#excel-preview-body .excel-row-check');
  const data = [];

  checks.forEach(cb => {
    if (!cb.checked) return;
    const idx = parseInt(cb.dataset.idx);
    const item = { ...pendingExcelData[idx] };

    // 从界面获取用户选择
    const card = document.querySelector(`.person-confirm-card[data-idx="${idx}"]`);
    if (card) {
      const selectedRadio = card.querySelector(`input[name="person-select-${idx}"]:checked`);
      if (selectedRadio) {
        if (selectedRadio.value === '__new__') {
          item.selected_person_id = null;
          const addrInput = card.querySelector('.new-person-address-input');
          if (addrInput) item.new_person_address = addrInput.value;
        } else {
          item.selected_person_id = parseInt(selectedRadio.value);
          item.new_person_address = '';
        }
      } else {
        showToast(`第${item.row_idx}行未选择人员，已跳过`, 'error');
        return;
      }
    } else {
      if (!item.selected_person_id) {
        const addrInput = document.querySelector(`.excel-new-person-fields[data-idx="${idx}"] .new-person-address-input`);
        if (addrInput) item.new_person_address = addrInput.value;
        if (item.new_person_address) {
          item.address = item.new_person_address;
        }
      }
    }

    if (item.new_person_address) {
      item.address = item.new_person_address;
    }

    data.push(item);
  });

  if (!data.length) { showToast('请至少选择一条记录', 'error'); return; }

  const unconfirmed = data.filter(d => d.needs_confirm && !d.selected_person_id && !d.new_person_address);
  if (unconfirmed.length > 0) {
    showToast(`有 ${unconfirmed.length} 条记录未选择人员`, 'error');
    return;
  }

  showImportLoading('正在导入数据...');

  try {
    const res = await api(API + '/api/import/excel-confirm', {
      method: 'POST', body: JSON.stringify({ data }),
    });
    if (!res) {
      hideImportLoading();
      return;
    }
    const result = await res.json();
    if (res.ok) {
      hideImportLoading();
      showToast(result.message || '导入成功');

      // 清除已导入的图片数据
      _photoResults[_currentPhotoIndex] = { ..._photoResults[_currentPhotoIndex], data: [], imported: true };

      // 跳到下一张未导入的图片
      let nextIndex = -1;
      for (let i = 0; i < _photoResults.length; i++) {
        if (_photoResults[i] && _photoResults[i].data && _photoResults[i].data.length > 0 && !_photoResults[i].imported) {
          nextIndex = i;
          break;
        }
      }

      if (nextIndex >= 0) {
        showPhotoResult(nextIndex);
        renderPhotoSwitcher();
      } else {
        // 全部导入完成，清空预览
        cancelImport();
        loadTransactions(1);
        loadSummary();
        loadPersonList();
      }
    } else {
      hideImportLoading();
      showToast(result.detail || '导入失败', 'error');
    }
  } catch (e) {
    hideImportLoading();
    showToast('导入出错: ' + e.message, 'error');
  }
}
