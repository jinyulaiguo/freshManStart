-- PostgreSQL 数据库结构定义 (Day 77 企业级 SQL Agent 沙箱)
-- 包含用户表 (users) 与 订单表 (orders)

DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    product VARCHAR(200) NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 种子数据插入 (20 条真实测试记录)
INSERT INTO users (name, email, status, last_login) VALUES
('Alice Smith', 'alice@enterprise.com', 'active', NOW() - INTERVAL '2 hours'),
('Bob Jones', 'bob@enterprise.com', 'active', NOW() - INTERVAL '1 day'),
('Charlie Brown', 'charlie@enterprise.com', 'inactive', NOW() - INTERVAL '30 days'),
('Diana Prince', 'diana@enterprise.com', 'active', NOW() - INTERVAL '5 minutes'),
('Ethan Hunt', 'ethan@enterprise.com', 'suspended', NOW() - INTERVAL '15 days'),
('Fiona Gallagher', 'fiona@enterprise.com', 'active', NOW() - INTERVAL '3 hours'),
('George Clark', 'george@enterprise.com', 'active', NOW() - INTERVAL '12 hours'),
('Hannah Abbott', 'hannah@enterprise.com', 'inactive', NOW() - INTERVAL '45 days');

INSERT INTO orders (user_id, product, amount, status, created_at) VALUES
(1, 'Enterprise AI Platform Subscription', 2999.00, 'completed', NOW() - INTERVAL '5 days'),
(1, 'LangGraph Advanced Workshop', 499.00, 'completed', NOW() - INTERVAL '2 days'),
(2, 'PostgreSQL Performance Optimization Guide', 199.00, 'completed', NOW() - INTERVAL '10 days'),
(2, 'Cloud Security Infrastructure License', 1500.00, 'completed', NOW() - INTERVAL '1 day'),
(3, 'Legacy System Migration Tool', 899.00, 'refunded', NOW() - INTERVAL '40 days'),
(4, 'AI Agent Orchestration Framework', 1299.00, 'completed', NOW() - INTERVAL '1 hour'),
(4, 'High-Throughput Vector DB Cluster', 3500.00, 'completed', NOW() - INTERVAL '30 minutes'),
(5, 'SecOps Automated Audit Suite', 2400.00, 'cancelled', NOW() - INTERVAL '20 days'),
(6, 'Python Asynchronous Microservices Architecture', 399.00, 'completed', NOW() - INTERVAL '4 hours'),
(6, 'Redis Enterprise In-Memory Cache Guide', 149.00, 'completed', NOW() - INTERVAL '2 hours'),
(7, 'Distributed Trace Monitoring Agent', 799.00, 'pending', NOW() - INTERVAL '6 hours'),
(8, 'Data Pipeline ETL Engine', 1199.00, 'completed', NOW() - INTERVAL '50 days');
