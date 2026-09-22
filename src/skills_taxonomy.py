"""
Skills taxonomy for TalentIQ.

A curated, categorized master list of skills/tools plus a synonym map so that
"ML" and "Machine Learning", or "JS" and "JavaScript", are recognized as the
same underlying skill. This directly answers the brief's "keyword-only search
misses good candidates" problem statement.
"""

SKILL_CATEGORIES = {
    "Programming Languages": [
        "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "C",
        "Go", "Golang", "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Scala",
        "R", "MATLAB", "Perl", "Objective-C", "Dart", "Shell Scripting",
        "SQL", "VBA",
    ],
    "Web & Frameworks": [
        "React", "React Native", "Angular", "Vue.js", "Node.js", "Express.js",
        "Django", "Flask", "FastAPI", "Spring Boot", "Spring", "ASP.NET",
        ".NET", "Ruby on Rails", "Laravel", "Next.js", "jQuery", "HTML",
        "CSS", "Sass", "Bootstrap", "Tailwind CSS", "GraphQL", "REST API",
        "WordPress", "Webpack",
    ],
    "Data & AI": [
        "Machine Learning", "Deep Learning", "Natural Language Processing",
        "Computer Vision", "Data Science", "Data Analysis", "Data Mining",
        "Data Engineering", "Statistics", "Predictive Modeling",
        "TensorFlow", "PyTorch", "Keras", "Scikit-learn", "Pandas", "NumPy",
        "OpenCV", "Hugging Face", "LLM", "Generative AI", "MLOps",
        "Big Data", "Apache Spark", "Hadoop", "ETL", "Data Warehousing",
        "Power BI", "Tableau", "Looker", "Excel", "A/B Testing",
        "Snowflake", "dbt", "Databricks",
    ],
    "Cloud & DevOps": [
        "AWS", "Amazon Web Services", "EC2", "S3", "SQS", "Azure", "Google Cloud Platform", "GCP",
        "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins",
        "CI/CD", "Git", "GitHub", "GitLab", "Linux", "Unix", "AIX", "AWK", "Autofs", "Apache Tomcat", "Bash",
        "Nginx", "Microservices", "Serverless", "DevOps",
        "Site Reliability Engineering", "Cloud Architecture",
    ],
    "Databases": [
        "MySQL", "PostgreSQL", "MongoDB", "Oracle", "SQL Server",
        "Redis", "Cassandra", "DynamoDB", "SQLite", "Elasticsearch",
        "Firebase", "Database Administration", "Database Design",
        "Data Modeling",
    ],
    "Mobile": [
        "iOS Development", "Android Development", "Flutter", "SwiftUI",
        "Mobile App Development", "Xamarin",
    ],
    "Design": [
        "UI/UX Design", "Figma", "Adobe XD", "Sketch", "Adobe Photoshop",
        "Adobe Illustrator", "InDesign", "Wireframing", "Prototyping",
        "User Research", "Graphic Design",
    ],
    "Project & Business": [
        "Project Management", "Agile", "Scrum", "Kanban", "JIRA",
        "Product Management", "Business Analysis", "Stakeholder Management",
        "Risk Management", "Budgeting", "Forecasting", "Salesforce",
        "SAP", "ERP", "CRM", "Six Sigma", "Change Management",
        "Vendor Management", "Contract Negotiation", "Strategic Planning",
    ],
    "Finance & Accounting": [
        "Financial Analysis", "Financial Modeling", "Accounting",
        "Bookkeeping", "QuickBooks", "Tax Preparation", "Auditing",
        "Accounts Payable", "Accounts Receivable", "Payroll",
        "Financial Reporting", "GAAP", "Investment Analysis",
    ],
    "HR & Recruiting": [
        "Talent Acquisition", "Recruiting", "Onboarding",
        "Employee Relations", "HRIS", "Performance Management",
        "Compensation and Benefits", "Workday", "Succession Planning",
        "Labor Relations", "HR Policy",
    ],
    "Sales & Marketing": [
        "Sales", "Business Development", "Digital Marketing", "SEO", "SEM",
        "Content Marketing", "Social Media Marketing", "Email Marketing",
        "Google Analytics", "Google Ads", "Brand Management",
        "Lead Generation", "Account Management", "Customer Relationship Management",
        "Market Research", "Copywriting",
    ],
    "Healthcare": [
        "Patient Care", "Clinical Documentation", "EHR", "EMR", "HIPAA",
        "Medical Coding", "Nursing", "Phlebotomy", "CPR Certified",
        "Patient Assessment",
    ],
    "Engineering & Manufacturing": [
        "AutoCAD", "SolidWorks", "CAD", "CNC Programming", "Lean Manufacturing",
        "Quality Assurance", "Quality Control", "Six Sigma",
        "Supply Chain Management", "Inventory Management", "Logistics",
        "Mechanical Design", "Electrical Engineering",
    ],
    "Soft Skills": [
        "Communication", "Leadership", "Teamwork", "Problem Solving",
        "Critical Thinking", "Time Management", "Adaptability",
        "Conflict Resolution", "Public Speaking", "Negotiation",
        "Attention to Detail", "Customer Service", "Mentoring",
        "Cross-functional Collaboration", "Decision Making",
    ],
    "Languages": [
        "Spanish", "French", "German", "Mandarin", "Japanese", "Arabic",
        "Portuguese", "Hindi", "Italian",
    ],
}

# Flat master list (unique, order preserved)
_seen = set()
MASTER_SKILLS = []
for _cat, _skills in SKILL_CATEGORIES.items():
    for _s in _skills:
        if _s.lower() not in _seen:
            _seen.add(_s.lower())
            MASTER_SKILLS.append(_s)

# Skill -> category lookup
SKILL_TO_CATEGORY = {
    s.lower(): cat for cat, skills in SKILL_CATEGORIES.items() for s in skills
}

# Synonym / abbreviation map: alias (lowercase) -> canonical skill name.
# This is the "semantic" layer that keyword-only search misses.
SYNONYMS = {
    "ml": "Machine Learning",
    "dl": "Deep Learning",
    "ai": "Machine Learning",
    "nlp": "Natural Language Processing",
    "cv": "Computer Vision",
    "js": "JavaScript",
    "ts": "TypeScript",
    "reactjs": "React",
    "react.js": "React",
    "react js": "React",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "vue js": "Vue.js",
    "vue": "Vue.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "node js": "Node.js",
    "node": "Node.js",
    "expressjs": "Express.js",
    "express.js": "Express.js",
    "express js": "Express.js",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "next js": "Next.js",
    "golang": "Go",
    "k8s": "Kubernetes",
    "aws cloud": "AWS",
    "amazon web services": "AWS",
    "gcp": "Google Cloud Platform",
    "google cloud": "Google Cloud Platform",
    "azure cloud": "Azure",
    "postgres": "PostgreSQL",
    "postgressql": "PostgreSQL",
    "mongo": "MongoDB",
    "mssql": "SQL Server",
    "ms sql server": "SQL Server",
    "py": "Python",
    "oop": "Object-Oriented Programming",
    "ci": "CI/CD",
    "cd": "CI/CD",
    "cicd": "CI/CD",
    "rest": "REST API",
    "restful api": "REST API",
    "restful apis": "REST API",
    "api": "REST API",
    "ux": "UI/UX Design",
    "ui": "UI/UX Design",
    "ui/ux": "UI/UX Design",
    "pm": "Project Management",
    "biz dev": "Business Development",
    "bd": "Business Development",
    "seo/sem": "SEO",
    "excel spreadsheets": "Excel",
    "aix": "AIX",
    "ms excel": "Excel",
    "powerbi": "Power BI",
    "power-bi": "Power BI",
    "tf": "TensorFlow",
    "sklearn": "Scikit-learn",
    "scikit learn": "Scikit-learn",
    "hr": "HR Policy",
    "crm software": "Customer Relationship Management",
    "erp software": "ERP",
    "qa": "Quality Assurance",
    "sql server management studio": "SQL Server",
    "github actions": "CI/CD",
    "gitlab ci": "CI/CD",
    "genai": "Generative AI",
    "gen ai": "Generative AI",
    "llms": "LLM",
    "large language models": "LLM",
    "split testing": "A/B Testing",
    "a/b test": "A/B Testing",
    "ab testing": "A/B Testing",
    "stakeholder collaboration": "Stakeholder Management",
    "stakeholder communication": "Stakeholder Management",
    "cross-functional leadership": "Cross-functional Collaboration",
    "cross functional collaboration": "Cross-functional Collaboration",
    "cross-functional teams": "Cross-functional Collaboration",
    "snow flake": "Snowflake",
    "amazon ec2": "EC2",
    "ec2": "EC2",
    "amazon s3": "S3",
    "s3": "S3",
    "amazon sqs": "SQS",
    "sqs": "SQS",
    "apache tomcat": "Apache Tomcat",
    "tomcat": "Apache Tomcat",
    "awk": "AWK",
    "auto mounts": "Autofs",
    "auto-mounts": "Autofs",
    "autofs": "Autofs",
}

def canonicalize(term: str) -> str:
    """Map a raw extracted token to its canonical skill name, if known."""
    key = term.strip().lower()
    if key in SYNONYMS:
        return SYNONYMS[key]
    for skill in MASTER_SKILLS:
        if skill.lower() == key:
            return skill
    return term.strip()
