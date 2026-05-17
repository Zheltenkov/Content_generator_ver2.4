// Curriculum CSV and project selector controller.
// Owns curriculum session state and exposes a small global contract for main.js.

let curriculumDirections = {
    "Бизнес аналитика": "BSA",
    "Кибербезопасность": "Cb",
    "DevOps": "DO",
    "Проектный менеджмент": "PjM",
    "Тестирование и обеспечение качества": "QA",
    "Машинное обучение": "DS"
};

let currentCurriculum = null;
let currentCurriculumContext = null;

function getCurriculumApiUrl() {
    const runtime = window.ContentGenGenerationRuntime || {};
    if (typeof runtime.getApiUrl === 'function') return runtime.getApiUrl();
    return window.ContentGenApiUrl || window.API_URL || `${window.location.origin}/api/v1`;
}

function getCurriculumAuthHeader() {
    const token = localStorage.getItem('auth_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
}

function getCurrentCurriculumContext() {
    if (currentCurriculumContext) return currentCurriculumContext;
    try {
        const savedContext = sessionStorage.getItem('curriculum_context');
        currentCurriculumContext = savedContext ? JSON.parse(savedContext) : null;
        return currentCurriculumContext;
    } catch (error) {
        console.warn('Failed to restore curriculum_context');
        return null;
    }
}

async function handleCurriculumUpload(event) {
    const fileInput = event && event.target ? event.target : null;
    const file = fileInput && fileInput.files ? fileInput.files[0] : null;
    if (!file) return;

    const fileNameEl = document.getElementById('curriculumFileName');
    if (fileNameEl) fileNameEl.textContent = 'Загрузка...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${getCurriculumApiUrl()}/curriculum/upload`, {
            method: 'POST',
            headers: getCurriculumAuthHeader(),
            body: formData
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Ошибка загрузки' }));
            throw new Error(error.detail || `Ошибка ${response.status}`);
        }

        currentCurriculum = await response.json();
        sessionStorage.setItem('curriculum_data', JSON.stringify(currentCurriculum));

        const directionCode = currentCurriculum.direction_code;
        const directionSelect = document.getElementById('direction');
        if (directionSelect && directionCode && directionCode !== 'UNK') {
            const hasOption = Array.from(directionSelect.options).some(opt => opt.value === directionCode);
            if (hasOption) directionSelect.value = directionCode;
        }

        populateCurriculumBlocks();
        const blockGroup = document.getElementById('curriculumBlockGroup');
        if (blockGroup) blockGroup.style.display = 'block';
        if (fileNameEl) {
            fileNameEl.textContent = `${file.name} (${currentCurriculum.blocks.length} блоков)`;
        }

        window.toast?.success(`УП загружен: ${currentCurriculum.direction} (${currentCurriculum.blocks.length} блоков)`);
        console.log('✅ УП загружен:', currentCurriculum);
    } catch (error) {
        if (fileNameEl) fileNameEl.textContent = `Ошибка: ${error.message}`;
        console.error('❌ Ошибка загрузки УП:', error);
        window.toast?.error(`Ошибка загрузки УП: ${error.message}`);
    }
}

function populateCurriculumBlocks() {
    const select = document.getElementById('curriculumBlock');
    if (!select || !currentCurriculum) return;

    select.innerHTML = '<option value="">-- Выберите блок --</option>';
    for (const block of currentCurriculum.blocks) {
        const option = document.createElement('option');
        option.value = block.name;
        option.textContent = block.name;
        option.dataset.goals = JSON.stringify(block.goals || []);
        select.appendChild(option);
    }
}

function onCurriculumBlockChange() {
    const blockSelect = document.getElementById('curriculumBlock');
    const projectGroup = document.getElementById('curriculumProjectGroup');
    const projectSelect = document.getElementById('curriculumProject');
    const blockName = blockSelect?.value || '';

    const thematicBlock = document.getElementById('thematicBlock');
    if (thematicBlock) thematicBlock.value = blockName;

    if (!blockName || !currentCurriculum || !projectGroup || !projectSelect) {
        if (projectGroup) projectGroup.style.display = 'none';
        return;
    }

    const block = currentCurriculum.blocks.find(b => b.name === blockName);
    if (!block) return;

    projectSelect.innerHTML = '<option value="">-- Выберите проект --</option>';
    for (const project of block.projects) {
        const option = document.createElement('option');
        option.value = project.order;
        option.textContent = `${project.order}. ${project.title}`;
        option.dataset.project = JSON.stringify(project);
        projectSelect.appendChild(option);
    }

    projectGroup.style.display = 'block';
}

function onCurriculumProjectChange() {
    const projectSelect = document.getElementById('curriculumProject');
    const selectedOption = projectSelect?.selectedOptions?.[0];
    if (!selectedOption || !selectedOption.dataset.project || !currentCurriculum) return;

    const project = JSON.parse(selectedOption.dataset.project);
    const blockName = document.getElementById('curriculumBlock')?.value || '';
    const block = currentCurriculum.blocks.find(b => b.name === blockName);
    if (!block) return;

    setCurriculumFieldValue('titleSeed', project.title || '');
    setCurriculumFieldValue('projectDescription', project.description || '');

    if (project.learning_outcomes && project.learning_outcomes.length > 0) {
        setCurriculumFieldValue('learningOutcomes', project.learning_outcomes.join('\n'));
    }

    setCurriculumFieldValue(
        'skills',
        project.skills && project.skills.length > 0 ? project.skills.join('\n') : ''
    );

    const audienceLevelEl = document.getElementById('audienceLevel');
    if (audienceLevelEl) {
        audienceLevelEl.value = window.normalizeAudienceLevel
            ? window.normalizeAudienceLevel(project.audience_level)
            : (project.audience_level || 'beginner_plus');
    }

    setCurriculumFieldValue(
        'requiredTools',
        project.required_tools && project.required_tools.length > 0 ? project.required_tools.join(', ') : ''
    );
    setCurriculumFieldValue('requiredSoftware', project.required_software || '');
    setCurriculumFieldValue('storytellingType', project.storytelling_type || 'sjm');
    window.updateStorytellingTypeHelp?.();
    setCurriculumFieldValue('storytelling', project.sjm || '');

    if (project.format) {
        setCurriculumFieldValue('projectType', project.format);
        window.toggleGroupSize?.();
    }
    if (project.group_size) {
        setCurriculumFieldValue('groupSize', project.group_size);
    }

    setCurriculumFieldValue('platformName', project.platform_name || project.title || '');
    setCurriculumFieldValue('workloadHours', project.workload_hours || '');
    setCurriculumFieldValue('additionalMaterials', project.additional_materials || '');

    if (block.code && block.code !== 'UNK') {
        setCurriculumFieldValue('direction', block.code);
    }

    currentCurriculumContext = buildCurriculumContext(block, project);
    sessionStorage.setItem('curriculum_context', JSON.stringify(currentCurriculumContext));

    console.log('✅ Данные проекта загружены из УП:', project.title);
    console.log('📋 Контекст УП:', currentCurriculumContext);
    window.toast?.success(`Загружен проект: ${project.title}`);
}

function setCurriculumFieldValue(id, value) {
    const element = document.getElementById(id);
    if (element) element.value = value ?? '';
}

function buildCurriculumContext(block, currentProject) {
    if (!currentCurriculum || !block || !currentProject) return null;

    const blockIndex = currentCurriculum.blocks.findIndex(b => b.name === block.name);
    const projectIndex = block.projects.findIndex(p => p.order === currentProject.order);

    const previousProjects = block.projects.slice(0, projectIndex).map(p => ({
        order: p.order,
        title: p.title,
        description: p.description,
        learning_outcomes: p.learning_outcomes || [],
        block_name: block.name
    }));

    const nextProjects = block.projects.slice(projectIndex + 1).map(p => ({
        order: p.order,
        title: p.title,
        description: p.description,
        learning_outcomes: p.learning_outcomes || [],
        block_name: block.name
    }));

    const allBlockLearningOutcomes = [];
    for (const project of block.projects) {
        if (project.learning_outcomes) {
            allBlockLearningOutcomes.push(...project.learning_outcomes);
        }
    }

    const crossBlockDepth = 2;
    let previousBlockProjects = [];
    let nextBlockProjects = [];

    if (blockIndex > 0) {
        const prevBlock = currentCurriculum.blocks[blockIndex - 1];
        previousBlockProjects = prevBlock.projects.slice(-crossBlockDepth).map(p => ({
            order: p.order,
            title: p.title,
            description: p.description,
            learning_outcomes: p.learning_outcomes || [],
            block_name: prevBlock.name
        }));
    }

    if (blockIndex < currentCurriculum.blocks.length - 1) {
        const nextBlock = currentCurriculum.blocks[blockIndex + 1];
        nextBlockProjects = nextBlock.projects.slice(0, crossBlockDepth).map(p => ({
            order: p.order,
            title: p.title,
            description: p.description,
            learning_outcomes: p.learning_outcomes || [],
            block_name: nextBlock.name
        }));
    }

    return {
        block_name: block.name,
        block_goals: block.goals || [],
        current_project_order: currentProject.order,
        current_project_description: currentProject.description || '',
        current_project_skills: currentProject.skills || [],
        current_project_audience_level: currentProject.audience_level || null,
        current_project_required_tools: currentProject.required_tools || [],
        current_project_required_software: currentProject.required_software || null,
        previous_projects: previousProjects,
        next_projects: nextProjects,
        all_block_learning_outcomes: [...new Set(allBlockLearningOutcomes)],
        previous_block_projects: previousBlockProjects,
        next_block_projects: nextBlockProjects,
        storytelling_type: currentProject.storytelling_type || 'sjm',
        sjm_context: currentProject.sjm || null,
        expert_development_notes: currentProject.expert_notes || null,
        additional_materials: currentProject.additional_materials || null
    };
}

function onDirectionChange() {
    const directionSelect = document.getElementById('direction');
    const addBlockExpander = document.getElementById('addBlockExpander');
    const thematicBlock = document.getElementById('thematicBlock');
    if (!directionSelect) return;

    if (directionSelect.value === 'ADD') {
        if (addBlockExpander) addBlockExpander.style.display = 'block';
    } else {
        if (addBlockExpander) addBlockExpander.style.display = 'none';
        if (thematicBlock) thematicBlock.value = directionSelect.value;
    }
}

function restoreCurriculumFromSession() {
    try {
        const savedCurriculum = sessionStorage.getItem('curriculum_data');
        if (savedCurriculum) {
            currentCurriculum = JSON.parse(savedCurriculum);
            populateCurriculumBlocks();
            const group = document.getElementById('curriculumBlockGroup');
            if (group) group.style.display = 'block';
            const fileName = document.getElementById('curriculumFileName');
            if (fileName) fileName.textContent = `${currentCurriculum.direction} (восстановлен из сессии)`;
            console.log('📚 УП восстановлен из сессии');
        }

        currentCurriculumContext = getCurrentCurriculumContext();
        if (currentCurriculumContext) {
            console.log('📋 Контекст УП восстановлен из сессии');
        }
    } catch (error) {
        console.warn('⚠️ Не удалось восстановить УП из сессии:', error);
    }
}

async function loadThematicBlocks() {
    try {
        const response = await fetch(`${getCurriculumApiUrl()}/thematic-blocks`);
        if (response.ok) {
            curriculumDirections = await response.json();
            window.thematicBlocks = curriculumDirections;
            updateDirectionSelect();
        }
    } catch (error) {
        console.log('Используем направления по умолчанию');
    }

    restoreCurriculumFromSession();
}

function updateDirectionSelect() {
    const select = document.getElementById('direction');
    if (!select) return;

    const currentValue = select.value;
    select.innerHTML = '';

    for (const [name, code] of Object.entries(curriculumDirections)) {
        const option = document.createElement('option');
        option.value = code;
        option.textContent = name;
        select.appendChild(option);
    }

    const addOption = document.createElement('option');
    addOption.value = 'ADD';
    addOption.textContent = 'Добавить';
    select.appendChild(addOption);

    if (currentValue && currentValue !== 'ADD') {
        select.value = currentValue;
    }

    select.onchange = onDirectionChange;
}

function updateThematicBlockSelect() {
    updateDirectionSelect();
}

async function addThematicBlock() {
    const name = document.getElementById('newBlockName')?.value.trim() || '';
    const code = document.getElementById('newBlockCode')?.value.trim() || '';

    if (!name) {
        alert('Введите название направления');
        return;
    }
    if (!code) {
        alert('Введите кодовое обозначение');
        return;
    }
    if (Object.values(curriculumDirections).includes(code)) {
        alert(`Кодовое обозначение '${code}' уже используется!`);
        return;
    }

    curriculumDirections[name] = code;
    window.thematicBlocks = curriculumDirections;
    updateDirectionSelect();
    setCurriculumFieldValue('direction', code);
    const addBlockExpander = document.getElementById('addBlockExpander');
    if (addBlockExpander) addBlockExpander.style.display = 'none';
    setCurriculumFieldValue('newBlockName', '');
    setCurriculumFieldValue('newBlockCode', '');

    try {
        await fetch(`${getCurriculumApiUrl()}/thematic-blocks`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...getCurriculumAuthHeader()
            },
            body: JSON.stringify(curriculumDirections)
        });
    } catch (error) {
        console.log('Не удалось сохранить тематические блоки на сервере');
    }
}

window.directions = curriculumDirections;
window.thematicBlocks = curriculumDirections;
Object.assign(window, {
    getCurrentCurriculumContext,
    handleCurriculumUpload,
    populateCurriculumBlocks,
    onCurriculumBlockChange,
    onCurriculumProjectChange,
    buildCurriculumContext,
    onDirectionChange,
    restoreCurriculumFromSession,
    loadThematicBlocks,
    updateDirectionSelect,
    updateThematicBlockSelect,
    addThematicBlock
});
