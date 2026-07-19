/* ========== 项目管理页面逻辑 ========== */

let regionTree = [];
let selectedRegions = [];

// ==================== 行政区划级联选择器 ====================

async function loadRegionTree() {
    try {
        const resp = await fetch('/api/regions/tree/');
        const data = await resp.json();
        regionTree = data.tree || [];
        const provSelect = document.getElementById('region-province');
        regionTree.forEach(prov => {
            provSelect.innerHTML += `<option value="${prov.code}">${prov.name}</option>`;
        });
    } catch (e) {
        console.error('加载行政区划数据失败:', e);
    }
}

function onProvinceChange() {
    const code = document.getElementById('region-province').value;
    document.getElementById('region-city').innerHTML = '<option value="">选择城市</option>';
    document.getElementById('region-county').innerHTML = '<option value="">选择区县</option>';
    document.getElementById('region-county').disabled = true;

    if (!code) {
        document.getElementById('region-city').disabled = true;
        return;
    }
    const prov = regionTree.find(p => p.code === code);
    if (!prov || !prov.children) {
        document.getElementById('region-city').disabled = true;
        return;
    }

    const prefectures = prov.children.filter(c => c.level === 'prefecture');
    const directCounties = prov.children.filter(c => c.level === 'county');

    if (prefectures.length) {
        prefectures.forEach(city => {
            document.getElementById('region-city').innerHTML +=
                `<option value="${city.code}">${city.name}</option>`;
        });
        document.getElementById('region-city').disabled = false;
    }

    if (directCounties.length) {
        directCounties.forEach(county => {
            document.getElementById('region-county').innerHTML +=
                `<option value="${county.code}">${county.name}</option>`;
        });
        document.getElementById('region-county').disabled = false;
        if (!prefectures.length) {
            document.getElementById('region-city').innerHTML = '<option value="">(无需选择)</option>';
            document.getElementById('region-city').disabled = true;
        }
    }
}

function onCityChange() {
    const provCode = document.getElementById('region-province').value;
    const cityCode = document.getElementById('region-city').value;
    const prov = regionTree.find(p => p.code === provCode);
    const directCounties = prov?.children?.filter(c => c.level === 'county') || [];
    document.getElementById('region-county').innerHTML = '<option value="">选择区县</option>';
    directCounties.forEach(county => {
        document.getElementById('region-county').innerHTML +=
            `<option value="${county.code}">${county.name}</option>`;
    });

    if (cityCode) {
        const city = prov?.children?.find(c => c.code === cityCode);
        if (city && city.children) {
            city.children.forEach(county => {
                document.getElementById('region-county').innerHTML +=
                    `<option value="${county.code}">${county.name}</option>`;
            });
        }
    }
    document.getElementById('region-county').disabled = false;
}

function onCountyChange() {
    // 占位，选好区县后直接点保存即可
}

function removeRegion(code) {
    selectedRegions = [];
    renderRegionTags();
}

function renderRegionTags() {
    document.getElementById('region-tags').innerHTML = selectedRegions.map(r =>
        `<span class="region-tag">${r.name}
            <span class="remove" onclick="removeRegion('${r.code}')">&times;</span>
        </span>`
    ).join('');
    // 已有区域 → 隐藏选择器；无区域 → 显示选择器
    document.getElementById('region-picker').style.display = selectedRegions.length ? 'none' : 'flex';
}

function resetRegionSelects() {
    document.getElementById('region-province').value = '';
    document.getElementById('region-city').innerHTML = '<option value="">选择城市</option>';
    document.getElementById('region-city').disabled = true;
    document.getElementById('region-county').innerHTML = '<option value="">选择区县</option>';
    document.getElementById('region-county').disabled = true;
}


// ==================== 弹窗操作 ====================

function showCreateModal() {
    document.getElementById('edit-project-id').value = '';
    document.getElementById('project-name').value = '';
    document.getElementById('project-desc').value = '';
    document.getElementById('project-status').value = 'recording';
    document.getElementById('project-color').value = '#1890FF';
    selectedRegions = [];
    renderRegionTags();
    resetRegionSelects();
    document.getElementById('modal-title').textContent = '新建项目';
    document.getElementById('project-modal').style.display = 'flex';
}

async function editProject(id) {
    try {
        const resp = await fetch(`/api/projects/${id}/jurisdiction/`);
        const data = await resp.json();
        document.getElementById('edit-project-id').value = id;
        document.getElementById('project-name').value = data.project_name || '';
        document.getElementById('project-desc').value = data.project_description || '';
        document.getElementById('project-status').value = data.project_status || 'recording';
        document.getElementById('project-color').value = data.fill_color || '#1890FF';
        selectedRegions = [];
        (data.region_list || []).forEach(r => {
            selectedRegions.push({ code: r.code, name: r.name });
        });
        renderRegionTags();
        resetRegionSelects();
        document.getElementById('modal-title').textContent = '编辑项目';
        document.getElementById('project-modal').style.display = 'flex';
    } catch (e) {
        console.error('加载项目数据失败:', e);
        alert('加载项目数据失败');
    }
}

function closeModal() {
    document.getElementById('project-modal').style.display = 'none';
}


// ==================== CRUD 操作 ====================

async function saveProject() {
    const id = document.getElementById('edit-project-id').value;
    const name = document.getElementById('project-name').value;
    if (!name.trim()) { alert('请输入项目名称'); return; }
    const desc = document.getElementById('project-desc').value;
    const status = document.getElementById('project-status').value;
    const color = document.getElementById('project-color').value;
    const url = id ? `/api/projects/${id}/update/` : '/api/projects/create/';

    // 如果标签区为空，自动从下拉框取选中值；否则用标签区
    let regionCodes = selectedRegions.map(r => r.code);
    if (!regionCodes.length) {
        const countyCode = document.getElementById('region-county').value;
        if (countyCode) {
            regionCodes = [countyCode];
        }
    }

    const body = { name, status, description: desc, jurisdiction_color: color, region_codes: regionCodes };

    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!data.ok) {
            alert('保存失败: ' + (data.error || '未知错误'));
            return;
        }
        location.reload();
    } catch (e) {
        alert('保存失败: ' + e.message);
    }
}

async function archiveProject(id) {
    if (!confirm('确定归档此项目？归档后不再接收数据。')) return;
    try {
        await fetch(`/api/projects/${id}/update/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({ status: 'archived' }),
        });
        location.reload();
    } catch (e) {
        alert('归档失败');
    }
}

async function deleteProject(id) {
    if (!confirm('确定删除此项目？将同时删除该项目下的所有设备数据。')) return;
    try {
        await fetch(`/api/projects/${id}/delete/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCookie('csrftoken') },
        });
        location.reload();
    } catch (e) {
        alert('删除失败');
    }
}

function exportCSV(id) {
    window.open(`/api/projects/${id}/export-csv/`, '_blank');
}


// ==================== 工具函数 ====================

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        for (let cookie of document.cookie.split(';')) {
            cookie = cookie.trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}


// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', loadRegionTree);
