// Generator form state helpers.
// This module owns DOM <-> generation seed mapping; main.js owns orchestration only.

        function callGeneratorFormHook(name) {
            const fn = window[name];
            if (typeof fn === 'function') {
                fn();
            }
        }

        function getInputValue(id, fallback = '') {
            const element = document.getElementById(id);
            return element ? element.value : fallback;
        }

        function getTrimmedValue(id) {
            return getInputValue(id, '').trim();
        }

        function splitLines(value) {
            return String(value || '')
                .split('\n')
                .map((item) => item.trim())
                .filter(Boolean);
        }

function restoreFormData(seed) {
            // Восстанавливаем значения полей формы
            if (seed.language) document.getElementById('language').value = seed.language;
            if (seed.project_type) document.getElementById('projectType').value = seed.project_type;
            if (seed.direction) setValue('direction', seed.direction);
            if (seed.thematic_block) document.getElementById('thematicBlock').value = seed.thematic_block;
            if (seed.audience_level) setAudienceLevel(seed.audience_level);
            if (seed.required_tools) document.getElementById('requiredTools').value = seed.required_tools.join(', ');
            if (seed.required_software) setValue(
                'requiredSoftware',
                Array.isArray(seed.required_software) ? seed.required_software.join(', ') : seed.required_software
            );
            if (seed.title_seed) document.getElementById('titleSeed').value = seed.title_seed;
            if (seed.project_description) document.getElementById('projectDescription').value = seed.project_description;
            if (seed.sjm) document.getElementById('storytelling').value = seed.sjm;
            if (seed.learning_outcomes) document.getElementById('learningOutcomes').value = seed.learning_outcomes.join('\n');
            if (seed.skills) document.getElementById('skills').value = seed.skills.join('\n');
            if (seed.group_size) document.getElementById('groupSize').value = seed.group_size;
            if (seed.repo_path_template) document.getElementById('repoPathTemplate').value = seed.repo_path_template;
            if (seed.repo_base_url) setValue('repoBaseUrl', seed.repo_base_url);
            if (seed.platform_name) setValue('platformName', seed.platform_name);
            if (seed.gitlab_link) setValue('gitlabLink', seed.gitlab_link);
            if (seed.workload_hours !== undefined && seed.workload_hours !== null) setValue('workloadHours', seed.workload_hours);
            if (seed.additional_materials) setValue('additionalMaterials', seed.additional_materials);
            if (seed.reference_project_hint) setValue('referenceProjectHint', seed.reference_project_hint);
            if (seed.reference_practice_hint) setValue('referencePracticeHint', seed.reference_practice_hint);
            if (seed.project_content_type) {
                setValue('projectContentType', seed.project_content_type === 'auto' ? '' : seed.project_content_type);
            } else if (seed.is_programming_project !== undefined && seed.is_programming_project !== null) {
                setValue('projectContentType', seed.is_programming_project ? 'hard_code' : 'no_code');
            }
            
            // Восстанавливаем чекбоксы
            setChecked('methodologyHumanReview', !!seed.methodology_human_review);
            setChecked('includeFormulas', !!seed.include_formulas);
            setChecked('includeTables', !!seed.include_tables);
            setChecked('includeDiagrams', !!seed.include_diagrams);
            if (seed.bonus_wish !== null && seed.bonus_wish !== undefined) {
                setChecked('generateBonus', true);
                setValue('bonusWish', seed.bonus_wish || '');
                callGeneratorFormHook('toggleBonusWish');
            }
            callGeneratorFormHook('toggleGroupSize');
            
        }
        // Направления (ранее thematicBlocks)

function fillFormFromData(data) {
            if (data.language) document.getElementById('language').value = data.language;
            if (data.project_type) {
                const projectType = data.project_type === 'индивидуальный' ? 'individual' : 
                                  data.project_type === 'групповой' ? 'group' : data.project_type;
                document.getElementById('projectType').value = projectType;
                callGeneratorFormHook('toggleGroupSize');
            }
            if (data.thematic_block || data.track) {
                document.getElementById('thematicBlock').value = data.thematic_block || data.track;
            }
            if (data.direction) setValue('direction', data.direction);
            if (data.audience_level) setAudienceLevel(data.audience_level);
            // Маппинг: project_title -> title_seed для обратной совместимости
            if (data.title_seed || data.project_title) {
                document.getElementById('titleSeed').value = data.title_seed || data.project_title;
            }
            if (data.required_tools) {
                document.getElementById('requiredTools').value = Array.isArray(data.required_tools) 
                    ? data.required_tools.join(', ') 
                    : data.required_tools;
            }
            if (data.required_software) {
                setValue(
                    'requiredSoftware',
                    Array.isArray(data.required_software) ? data.required_software.join(', ') : data.required_software
                );
            }
            if (data.sjm) document.getElementById('storytelling').value = data.sjm;
            if (data.methodology_human_review !== undefined) {
                setChecked('methodologyHumanReview', !!data.methodology_human_review);
            }
            if (data.project_description) document.getElementById('projectDescription').value = data.project_description;
            if (data.learning_outcomes) {
                document.getElementById('learningOutcomes').value = Array.isArray(data.learning_outcomes)
                    ? data.learning_outcomes.join('\n')
                    : data.learning_outcomes;
            }
            if (data.skills) {
                document.getElementById('skills').value = Array.isArray(data.skills)
                    ? data.skills.join('\n')
                    : data.skills;
            }
            if (data.group_size) {
                document.getElementById('groupSize').value = data.group_size;
                callGeneratorFormHook('toggleGroupSize');
            }
            if (data.repo_base_url) document.getElementById('repoBaseUrl').value = data.repo_base_url;
            if (data.repo_path_template) document.getElementById('repoPathTemplate').value = data.repo_path_template;
            if (data.platform_name) setValue('platformName', data.platform_name);
            if (data.gitlab_link) setValue('gitlabLink', data.gitlab_link);
            if (data.workload_hours !== undefined && data.workload_hours !== null) setValue('workloadHours', data.workload_hours);
            if (data.additional_materials) setValue('additionalMaterials', data.additional_materials);
            if (data.reference_project_hint) setValue('referenceProjectHint', data.reference_project_hint);
            if (data.reference_practice_hint) setValue('referencePracticeHint', data.reference_practice_hint);
            if (data.project_content_type) {
                setValue('projectContentType', data.project_content_type === 'auto' ? '' : data.project_content_type);
            } else if (data.is_programming_project !== undefined && data.is_programming_project !== null) {
                setValue('projectContentType', data.is_programming_project ? 'hard_code' : 'no_code');
            }
            setChecked('includeFormulas', !!data.include_formulas);
            setChecked('includeTables', !!data.include_tables);
            setChecked('includeDiagrams', !!data.include_diagrams);
            if (data.bonus_wish) {
                setChecked('generateBonus', true);
                setValue('bonusWish', data.bonus_wish);
                callGeneratorFormHook('toggleBonusWish');
            }
        }

        function applyOptionalTextSeedField(seed, fieldId, seedKey) {
            const value = getTrimmedValue(fieldId);
            if (value) {
                seed[seedKey] = value;
            } else {
                delete seed[seedKey];
            }
        }

        function applyOptionalNumberSeedField(seed, fieldId, seedKey, parser) {
            const rawValue = getTrimmedValue(fieldId);
            if (!rawValue) {
                delete seed[seedKey];
                return;
            }
            const value = parser(rawValue);
            if (!Number.isNaN(value)) {
                seed[seedKey] = value;
            }
        }

        function readCurriculumContext(explicitContext = null) {
            if (explicitContext) return explicitContext;
            try {
                const savedContext = sessionStorage.getItem('curriculum_context');
                return savedContext ? JSON.parse(savedContext) : null;
            } catch (error) {
                console.warn('Failed to restore curriculum_context');
                return null;
            }
        }

        function applySelectedCurriculumProject(seed) {
            const curriculumProjectSelect = document.getElementById('curriculumProject');
            if (!curriculumProjectSelect || !curriculumProjectSelect.value) return;
            const selectedOption = curriculumProjectSelect.selectedOptions[0];
            if (!selectedOption || !selectedOption.dataset.project) return;
            try {
                const projectData = JSON.parse(selectedOption.dataset.project);
                if (projectData.platform_name) seed.platform_name = projectData.platform_name;
                if (projectData.gitlab_link) seed.gitlab_link = projectData.gitlab_link;
                if (projectData.workload_hours !== undefined && projectData.workload_hours !== null) {
                    seed.workload_hours = projectData.workload_hours;
                }
                if (projectData.additional_materials) seed.additional_materials = projectData.additional_materials;
                if (!seed.sjm && projectData.sjm) seed.sjm = projectData.sjm;
            } catch (error) {
                console.warn('Failed to parse selected curriculum project:', error);
            }
        }

        function buildGenerationSeed({ curriculumContext = null } = {}) {
            const directionValue = getInputValue('direction');
            const thematicBlockValue = getInputValue('thematicBlock') || getInputValue('curriculumBlock');
            const seed = {
                language: getInputValue('language'),
                project_type: getInputValue('projectType'),
                direction: directionValue !== 'ADD' ? directionValue : '',
                thematic_block: thematicBlockValue || directionValue,
                audience_level: normalizeAudienceLevel(getInputValue('audienceLevel')),
                required_tools: splitCommaList(getInputValue('requiredTools')),
                required_software: splitCommaList(getInputValue('requiredSoftware')),
                title_seed: getInputValue('titleSeed'),
                project_description: getInputValue('projectDescription'),
                learning_outcomes: splitLines(getInputValue('learningOutcomes')),
                skills: splitLines(getInputValue('skills')),
                sjm: getTrimmedValue('storytelling') || null,
                methodology_human_review: getChecked('methodologyHumanReview'),
                include_formulas: getChecked('includeFormulas'),
                include_tables: getChecked('includeTables'),
                include_diagrams: getChecked('includeDiagrams'),
            };

            const projectContentType = getInputValue('projectContentType');
            if (projectContentType) {
                seed.project_content_type = projectContentType;
                seed.is_programming_project = projectContentType === 'hard_code'
                    ? true
                    : projectContentType === 'no_code'
                        ? false
                        : null;
            }

            applyOptionalTextSeedField(seed, 'referenceProjectHint', 'reference_project_hint');
            applyOptionalTextSeedField(seed, 'referencePracticeHint', 'reference_practice_hint');

            const resolvedCurriculumContext = readCurriculumContext(curriculumContext);
            if (resolvedCurriculumContext) seed.curriculum_context = resolvedCurriculumContext;
            applySelectedCurriculumProject(seed);

            applyOptionalTextSeedField(seed, 'platformName', 'platform_name');
            applyOptionalTextSeedField(seed, 'gitlabLink', 'gitlab_link');
            applyOptionalTextSeedField(seed, 'additionalMaterials', 'additional_materials');
            applyOptionalNumberSeedField(seed, 'workloadHours', 'workload_hours', parseFloat);

            if (seed.project_type === 'group') {
                seed.group_size = parseInt(getInputValue('groupSize'), 10);
            }
            applyOptionalTextSeedField(seed, 'repoBaseUrl', 'repo_base_url');
            applyOptionalTextSeedField(seed, 'repoPathTemplate', 'repo_path_template');

            seed.bonus_wish = getChecked('generateBonus') ? (getTrimmedValue('bonusWish') || '') : null;
            return seed;
        }


        if (typeof window !== 'undefined') {
            Object.assign(window, {
                restoreFormData,
                fillFormFromData,
                buildGenerationSeed,
            });
        }

