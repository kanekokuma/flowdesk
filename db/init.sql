SET NAMES utf8mb4;

CREATE TABLE positions (
  id VARCHAR(20) PRIMARY KEY,
  name VARCHAR(50) NOT NULL,
  approval_level INT NOT NULL DEFAULT 0,
  can_approve BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE departments (
  id VARCHAR(20) PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  manager_employee_id VARCHAR(20) NULL
);

CREATE TABLE sections (
  id VARCHAR(20) PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  department_id VARCHAR(20) NOT NULL,
  manager_employee_id VARCHAR(20) NULL,
  FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE employees (
  id VARCHAR(20) PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  email VARCHAR(120) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  department_id VARCHAR(20) NOT NULL,
  section_id VARCHAR(20) NOT NULL,
  position_id VARCHAR(20) NOT NULL,
  is_admin BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  FOREIGN KEY (department_id) REFERENCES departments(id),
  FOREIGN KEY (section_id) REFERENCES sections(id),
  FOREIGN KEY (position_id) REFERENCES positions(id)
);

ALTER TABLE departments
  ADD CONSTRAINT fk_departments_manager FOREIGN KEY (manager_employee_id) REFERENCES employees(id);

ALTER TABLE sections
  ADD CONSTRAINT fk_sections_manager FOREIGN KEY (manager_employee_id) REFERENCES employees(id);

CREATE TABLE application_types (
  id VARCHAR(20) PRIMARY KEY,
  name VARCHAR(50) NOT NULL,
  description VARCHAR(255) NOT NULL,
  requires_amount BOOLEAN NOT NULL DEFAULT FALSE,
  requires_target_date BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE application_type_approval_routes (
  application_type_id VARCHAR(20) NOT NULL,
  step_no INT NOT NULL,
  position_id VARCHAR(20) NOT NULL,
  PRIMARY KEY (application_type_id, step_no),
  FOREIGN KEY (application_type_id) REFERENCES application_types(id) ON DELETE CASCADE,
  FOREIGN KEY (position_id) REFERENCES positions(id)
);

CREATE TABLE applications (
  id INT AUTO_INCREMENT PRIMARY KEY,
  application_type_id VARCHAR(20) NOT NULL,
  applicant_id VARCHAR(20) NOT NULL,
  title VARCHAR(120) NOT NULL,
  amount DECIMAL(12, 0) NULL,
  target_date DATE NULL,
  detail_json TEXT NULL,
  returned_fields_json TEXT NULL,
  reason TEXT NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'pending',
  current_step_no INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (application_type_id) REFERENCES application_types(id),
  FOREIGN KEY (applicant_id) REFERENCES employees(id)
);

CREATE TABLE approval_steps (
  id INT AUTO_INCREMENT PRIMARY KEY,
  application_id INT NOT NULL,
  step_no INT NOT NULL,
  approver_id VARCHAR(20) NOT NULL,
  role_label VARCHAR(50) NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'not_reached',
  acted_at DATETIME NULL,
  comment TEXT NULL,
  UNIQUE KEY uq_approval_step (application_id, step_no),
  FOREIGN KEY (application_id) REFERENCES applications(id),
  FOREIGN KEY (approver_id) REFERENCES employees(id)
);

CREATE TABLE application_templates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  employee_id VARCHAR(20) NOT NULL,
  name VARCHAR(120) NOT NULL,
  application_type_id VARCHAR(20) NOT NULL,
  form_json TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(id),
  FOREIGN KEY (application_type_id) REFERENCES application_types(id)
);

CREATE TABLE approval_histories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  application_id INT NOT NULL,
  step_no INT NULL,
  actor_id VARCHAR(20) NOT NULL,
  action VARCHAR(30) NOT NULL,
  comment TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (application_id) REFERENCES applications(id),
  FOREIGN KEY (actor_id) REFERENCES employees(id)
);

CREATE TABLE notifications (
  id INT AUTO_INCREMENT PRIMARY KEY,
  employee_id VARCHAR(20) NOT NULL,
  application_id INT NULL,
  message VARCHAR(255) NOT NULL,
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(id),
  FOREIGN KEY (application_id) REFERENCES applications(id)
);

INSERT INTO positions (id, name, approval_level, can_approve) VALUES
  ('POS001', '一般社員', 0, FALSE),
  ('POS003', '課長', 2, TRUE),
  ('POS004', '部長', 3, TRUE),
  ('POS005', '役員', 4, TRUE),
  ('POS006', '経理責任者', 3, TRUE),
  ('POS007', '購買担当', 2, TRUE);

INSERT INTO departments (id, name, manager_employee_id) VALUES
  ('DEPT001', '営業部', NULL),
  ('DEPT002', '管理部', NULL);

INSERT INTO sections (id, name, department_id, manager_employee_id) VALUES
  ('SEC001', '営業1課', 'DEPT001', NULL),
  ('SEC002', '経理課', 'DEPT002', NULL),
  ('SEC003', '購買課', 'DEPT002', NULL);

INSERT INTO employees (id, name, email, password_hash, department_id, section_id, position_id, is_admin, is_active) VALUES
  ('EMP001', '山田 太郎', 'yamada@example.com', 'pbkdf2:sha256:1000000$workflowdemo$959bbbe223ac4079a25b3b7991e1c2fe927e6be500d842310d6d1dbf5814d12b', 'DEPT001', 'SEC001', 'POS001', FALSE, TRUE),
  ('EMP005', '佐藤 課長', 'sato@example.com', 'pbkdf2:sha256:1000000$workflowdemo$959bbbe223ac4079a25b3b7991e1c2fe927e6be500d842310d6d1dbf5814d12b', 'DEPT001', 'SEC001', 'POS003', FALSE, TRUE),
  ('EMP010', '鈴木 部長', 'suzuki@example.com', 'pbkdf2:sha256:1000000$workflowdemo$959bbbe223ac4079a25b3b7991e1c2fe927e6be500d842310d6d1dbf5814d12b', 'DEPT001', 'SEC001', 'POS004', FALSE, TRUE),
  ('EMP020', '田中 経理責任者', 'tanaka@example.com', 'pbkdf2:sha256:1000000$workflowdemo$959bbbe223ac4079a25b3b7991e1c2fe927e6be500d842310d6d1dbf5814d12b', 'DEPT002', 'SEC002', 'POS006', FALSE, TRUE),
  ('EMP030', '高橋 購買担当', 'takahashi@example.com', 'pbkdf2:sha256:1000000$workflowdemo$959bbbe223ac4079a25b3b7991e1c2fe927e6be500d842310d6d1dbf5814d12b', 'DEPT002', 'SEC003', 'POS007', FALSE, TRUE),
  ('EMP900', '伊藤 役員', 'ito@example.com', 'pbkdf2:sha256:1000000$workflowdemo$959bbbe223ac4079a25b3b7991e1c2fe927e6be500d842310d6d1dbf5814d12b', 'DEPT002', 'SEC002', 'POS005', FALSE, TRUE),
  ('ADMIN', '管理者', 'admin@example.com', 'pbkdf2:sha256:1000000$workflowdemo$959bbbe223ac4079a25b3b7991e1c2fe927e6be500d842310d6d1dbf5814d12b', 'DEPT002', 'SEC002', 'POS006', TRUE, TRUE);

UPDATE departments SET manager_employee_id = 'EMP010' WHERE id = 'DEPT001';
UPDATE departments SET manager_employee_id = 'EMP020' WHERE id = 'DEPT002';
UPDATE sections SET manager_employee_id = 'EMP005' WHERE id = 'SEC001';
UPDATE sections SET manager_employee_id = 'EMP020' WHERE id = 'SEC002';
UPDATE sections SET manager_employee_id = 'EMP030' WHERE id = 'SEC003';

INSERT INTO application_types (id, name, description, requires_amount, requires_target_date) VALUES
  ('APP_TYPE_001', '経費申請', '交通費、接待費、備品購入費などの精算・支出を申請する', TRUE, FALSE),
  ('APP_TYPE_002', '購買申請', '備品・機器・サービスなどの購入を申請する', TRUE, FALSE),
  ('APP_TYPE_003', '勤怠申請', '休暇・残業・休日出勤・打刻修正などを申請する', FALSE, TRUE),
  ('APP_TYPE_004', '稟議申請', '契約・投資・採用・価格変更など重要事項を申請する', TRUE, FALSE),
  ('APP_TYPE_005', '交通費申請', '通勤以外の業務移動にかかった交通費を申請する', TRUE, FALSE),
  ('APP_TYPE_006', '在宅勤務申請', '在宅勤務の実施日、勤務場所、予定業務を申請する', FALSE, TRUE);
