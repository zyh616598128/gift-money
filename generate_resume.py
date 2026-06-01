from fpdf import FPDF

class ResumePDF(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        font_path = 'C:/Windows/Fonts/simhei.ttf'
        self.add_font('SimHei', '', font_path)
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(18, 15, 18)

    def draw_line(self):
        self.set_draw_color(180, 180, 180)
        self.line(18, self.get_y(), 192, self.get_y())
        self.ln(3)

    def section_title(self, title):
        self.ln(4)
        self.set_font('SimHei', '', 13)
        self.set_text_color(41, 128, 185)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.draw_line()

    def body_text(self, text):
        self.set_font('SimHei', '', 10)
        self.set_text_color(60, 60, 60)
        self.multi_cell(0, 5.5, text, new_x="LMARGIN", new_y="NEXT")

    def bullet_text(self, text):
        self.set_font('SimHei', '', 10)
        self.set_text_color(60, 60, 60)
        self.set_x(22)
        self.cell(4, 5.5, '-')
        self.multi_cell(0, 5.5, text, new_x="LMARGIN", new_y="NEXT")

    def job_header(self, company, period, role):
        self.set_font('SimHei', '', 11)
        self.set_text_color(44, 62, 80)
        self.cell(0, 6, company, new_x="LMARGIN", new_y="NEXT")
        self.set_font('SimHei', '', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'{period}  |  {role}', new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def tech_item(self, title, content):
        self.set_font('SimHei', '', 10)
        self.set_text_color(44, 62, 80)
        self.cell(30, 5.5, f'{title}:', new_x="RIGHT")
        self.set_text_color(60, 60, 60)
        self.multi_cell(0, 5.5, content, new_x="LMARGIN", new_y="NEXT")

pdf = ResumePDF()
pdf.add_page()

# ===== 头部 =====
pdf.set_font('SimHei', '', 24)
pdf.set_text_color(44, 62, 80)
pdf.cell(0, 12, '朱银杭', new_x="LMARGIN", new_y="NEXT", align='C')
pdf.ln(2)

pdf.set_font('SimHei', '', 10)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 5, '南开大学  |  本科  |  29岁  |  男', new_x="LMARGIN", new_y="NEXT", align='C')
pdf.cell(0, 5, '131-6991-9816  |  616598128@qq.com  |  深圳市', new_x="LMARGIN", new_y="NEXT", align='C')
pdf.ln(4)
pdf.draw_line()

# ===== 求职意向 =====
pdf.section_title('求职意向')
pdf.body_text('期望职位: Java研发工程师          期望地点: 深圳          期望薪资: 面议')
pdf.body_text('工作年限: 6年          上份工作: 月薪22k + 年终奖2-4个月')

# ===== 技术栈 =====
pdf.section_title('技术栈')
tech = [
    ('后端开发', 'Java 8/11、Spring Boot、Spring Cloud、MyBatis-Plus、RESTful API'),
    ('大数据', 'Flink实时数据采集/清洗/分析、日志监控平台、流处理任务开发'),
    ('数据存储', 'MySQL/PostgreSQL、Redis缓存、Kafka/RabbitMQ消息中间件'),
    ('微服务', '微服务拆分部署、Nacos服务治理、多线程并发、高并发处理'),
    ('全栈', 'HTML/CSS/JS、FastAPI(Python)、SQLite、Vue(了解)'),
    ('AI集成', '大模型API、Vision图像识别、SSE流式响应、Prompt工程'),
    ('运维', 'Git、Maven、Docker、Jenkins、Shell、Linux'),
]
for t, c in tech:
    pdf.tech_item(t, c)

# ===== 工作经历 =====
pdf.section_title('工作经历')

pdf.job_header('独立开发（AI应用研究）', '2025.10 - 至今', '全栈开发工程师')
for b in [
    '独立设计开发礼金管理系统(FastAPI+原生JS)，支持CRUD、Excel/AI导入',
    '集成AI Vision API实现照片识别，SSE流式响应，图片压缩优化',
    'SQLite数据库优化(WAL模式/复合索引)，移动端响应式设计',
    '已上线(http://203.195.195.23)，迭代60+次',
]:
    pdf.bullet_text(b)
pdf.ln(3)

pdf.job_header('外企德科（华为云监控项目驻场）', '2022.10 - 2025.10', 'Java研发工程师')
for b in [
    '负责数据可观测全流程模块开发，日均20亿+监控数据的采集、分析、告警与可视化',
    '基于Flink实现监控/日志数据实时统计分析，开发流处理任务并维护线上稳定性',
    '参与告警规则引擎设计优化，支持多维度告警聚合、降噪、分级推送',
    '全流程参与需求对接、编码、测试联调、线上问题排查与服务部署',
    '连续3次获得A级绩效评价（年终奖4个月），月薪22k',
]:
    pdf.bullet_text(b)
pdf.ln(3)

pdf.job_header('高伟达（建行旗下存房系统）', '2020.12 - 2022.10', 'Java后端工程师')
for b in [
    '参与建行房屋租赁系统微服务开发，系统供全国总/分子公司/运营商使用',
    '负责用户权限、房屋交割、房源发布等核心模块，独立开发筹开模块',
    '使用RabbitMQ异步消息推送优化业务流程，Feign跨服务调用与HTTP对接',
    '参与数据库变更评审、XXL-Job定时任务、Nacos配置管理与服务部署',
    '负责16张业务源表卸数功能，使用反射实现通用卸数工具',
]:
    pdf.bullet_text(b)
pdf.ln(3)

pdf.job_header('广州菁人教育', '2018.12 - 2020.07', '高中数学教师')
pdf.bullet_text('制定课时计划、编写教案、授课，培训新教师')

# ===== 自我评价 =====
pdf.section_title('自我评价')
for e in [
    '6年软件开发经验，熟悉企业级业务系统开发，能快速融入团队',
    '逻辑思维强，对新技术有好奇心，持续学习AI与大模型应用',
    '具备高并发系统开发经验(日均20亿+数据)，注重代码质量与性能',
    '全流程参与需求对接、编码、测试、线上问题处理，工程化能力扎实',
    '乐于沟通协作，英语阅读良好，能阅读英文技术文档',
]:
    pdf.bullet_text(e)

pdf.output('D:/workspace/gift-money/resume_new.pdf')
print('PDF generated successfully!')
