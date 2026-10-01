# 🍭 Popssibilities — Project Charter

### Digital Modernization & Catering Management System

> **In one sentence:** We're replacing Popssibilities' manual, text-and-spreadsheet catering process with a modern website and an online ordering system that prices orders, collects event details, and sends emails and calendar invites automatically.

| | |
|---|---|
| **Client** | Popssibilities (Houston, TX) |
| **Sponsor** | Audrey Hu-Gonzalez, Owner |
| **Project Manager** | Kelly Vo |
| **Timeline** | 6 weeks |
| **Main deliverables** | Catering order system · Admin dashboard · Redesigned website · Automated workflows · Shopify review · Chatbot prototype (optional) |

---

## 📑 Table of Contents

1. [Client Organization & Contact Information](#1-client-organization--contact-information)
2. [Project Team & Roles](#2-project-team--roles)
3. [Project Purpose](#3-project-purpose)
4. [Project Objectives](#4-project-objectives)
5. [Business Needs](#5-business-needs)
6. [Project Justification](#6-project-justification)
7. [Project Scope Statement](#7-project-scope-statement)
8. [Out of Scope](#8-out-of-scope)
9. [High-Level Requirements](#9-high-level-requirements-initial-set)
10. [Key Milestones & Schedule](#10-key-milestones--high-level-schedule-6-weeks)
11. [Assumptions & Constraints](#11-initial-assumptions--constraints)
12. [Known Risks](#12-initial--known-risks)
13. [Project Success Criteria](#13-project-success-criteria)

---

## 1. Client Organization & Contact Information

| Field | Details |
|---|---|
| **Organization** | Popssibilities (Houston, TX) |
| **Sponsor / Client Contact** | Audrey Hu-Gonzalez, Owner |
| **Email** | [info@popssibilities.com](mailto:info@popssibilities.com) |
| **Phone** | 281-248-7514 |

---

## 2. Project Team & Roles

| Role | Team Member(s) |
|---|---|
| 🧭 Project Manager | Kelly Vo |
| 🗂️ Assistant Project Manager | Adriana Gonzalez |
| 💻 Lead Developer | Isaac Hernandez |
| 🎨 Frontend Developers | Aneena Paul, Dillion Nguyen |
| ⚙️ Backend Developers | Anh Hyunh, Shourya Sai Macha |
| 🗄️ Database Architect | Bryson Hawthorne |

---

## 3. Project Purpose

Popssibilities wants to **modernize its customer ordering workflow**, **reduce manual coordination**, and give catering clients a **seamless digital experience**.

The project will deliver:

- A redesigned website
- An online catering order management system
- Automated workflows that improve operational efficiency and customer satisfaction

---

## 4. Project Objectives

| # | Objective | What it means |
|---|---|---|
| 1 | **Build the online catering order system** | Automates pricing, captures detailed event information, and streamlines the customer ordering experience. |
| 2 | **Automate communication** | Order confirmations, contract delivery, business notifications, and Google Calendar scheduling. |
| 3 | **Redesign the website** | A colorful, expressive, clean, mobile-friendly site that reflects the brand and supports the new ordering system. |
| 4 | **Review Shopify feasibility** | Evaluate future scalability and integration opportunities. |
| 5 | **Deliver documentation & training** | Documentation, testing materials, and training resources for long-term use. |

---

## 5. Business Needs

### 😓 How it works today

Catering orders are handled **manually** through text messages, spreadsheets, and ad hoc communication. This causes:

- Inconsistent pricing
- Missed details
- Scheduling challenges
- Time-intensive coordination

### ✅ What the business needs

A **centralized digital system** that:

- Automates pricing
- Captures event details
- Manages custom popsicle requests
- Streamlines communication with clients

---

## 6. Project Justification

A modernized digital system will:

- 📉 **Reduce** administrative burden
- 🎯 **Improve** accuracy
- 😊 **Enhance** the customer experience
- 📈 **Support** business growth

Automating pricing, scheduling, and communication lets Popssibilities **handle more events efficiently** while keeping service quality high. The redesigned website will **strengthen brand identity** and **improve customer engagement**.

---

## 7. Project Scope Statement

### 💲 Key Business Rules at a Glance

| Rule | Value |
|---|---|
| Minimum order | **50 popsicles** |
| Delivery fee (within 30 miles) | **\$25 – \$75** |
| Dry ice | **\$15 per block** |
| Deposit | **50%** (via PayPal, Square, or Venmo) |
| Final payment reminder | **7 days before the event** |

### ✅ In Scope

#### 1️⃣ Catering Order Management System

An online ordering form with:

- Minimum order validation (50 popsicles)
- Quantity-based pricing logic
- Heart-shaped popsicle pricing
- Custom popsicle request text box (flavors, add-ons)
- Event details text box
- Delivery vs. full-service selection
- Delivery cost calculator (within 30 miles: \$25 – \$75)
- Dry ice calculator (\$15/block)
- Dynamic pricing calculator / sliding tool
- 50% deposit workflow (via external payment apps — PayPal, Square, Venmo)
- Final payment reminder (7 days before event)
- Customer login page *(optional)* — view order history or reorder

#### 2️⃣ Administrative Dashboard

An internal dashboard with:

- **Admin login page** *(required)*
- View and manage incoming orders
- Access customer information and event details
- Track delivery vs. full-service logistics
- Popsicle quantity tracking — basic inventory awareness *(optional)*
- Calendar view of upcoming events
- Exportable order summaries

#### 3️⃣ Customer Website Redesign

| Page / Feature | Contents |
|---|---|
| 🏠 Home | Brand story, mission, owner introduction |
| 🍦 Menu | Menu with photos |
| 📦 Catering | Ordering workflow |
| 📬 Contact | Instagram, Facebook, email |
| 🔐 Login button | Integrated customer + admin login |

**Design goals:** colorful, expressive, clean UI · mobile responsive

#### 4️⃣ Automated Workflows & Integrations

System-triggered automations:

| Automation | What it does |
|---|---|
| 📧 Client email | Sends the order summary + contract link |
| 📧 Business email | Sends the event details to Popssibilities |
| 📅 Google Calendar | Creates the event automatically |
| ⏰ Reminders | Final payment and final popsicle count |

#### 5️⃣ Shopify Feasibility Review

Research Shopify's ordering, inventory, and payment options:

- Evaluate checkout and ordering capabilities
- Review inventory management features
- Assess payment processing limitations
- Determine integration feasibility
- **Deliverable:** a recommendation report

#### 6️⃣ AI Chatbot *(Optional — Prototype Only)*

- FAQ responses
- Menu inquiries
- Basic catering questions
- ⚠️ Informational only — **no ordering or payment processing**

---

## 8. Out of Scope

The following will **not** be part of this project:

- ❌ Storing or processing credit card information
- ❌ Internal POS system
- ❌ Full Shopify migration
- ❌ Native mobile app development
- ❌ Legal contract review
- ❌ Accounting system integration

---

## 9. High-Level Requirements (Initial Set)

| ID | Requirement |
|---|---|
| **R1** | System must enforce a minimum order of 50 popsicles. |
| **R2** | System must calculate pricing based on quantity tiers. |
| **R3** | System must allow custom popsicle flavor and add-on input. |
| **R4** | System must capture event details (type, location, time). |
| **R5** | System must calculate delivery and dry ice costs. |
| **R6** | System must allow clients to submit a 50% deposit via an external payment app. |
| **R7** | System must generate automated emails for the client and the business. |
| **R8** | System must create Google Calendar events automatically. |
| **R9** | Website must include the menu, contact info, and catering workflow. |
| **R10** | Website must be mobile responsive and visually aligned with brand identity. |

---

## 10. Key Milestones & High-Level Schedule (6 Weeks)

| Week | Phase | Focus |
|:---:|---|---|
| **1** | 🔍 Discover | Requirements gathering, business rules validation, UX research |
| **2** | ✏️ Design | Wireframes, architecture planning, website layout |
| **3** | 🛠️ Build — Core | Ordering form development, pricing calculator, database design |
| **4** | 🔗 Build — Automation | Workflow automation (emails, calendar), external payment integration |
| **5** | 🧪 Content & Testing | Website content upload, testing, chatbot prototype |
| **6** | 🚀 Launch Prep | Final QA, user acceptance testing, training, final presentation |

---

## 11. Initial Assumptions & Constraints

### 📌 Assumptions

- The client is available weekly for feedback.
- External payment apps (PayPal, Square, Venmo) will be used for deposits.
- Google Calendar API access will be granted.
- Team members have basic web development experience.

### 🚧 Constraints

- 6-week project timeline.
- No credit card storage is allowed.
- Limited developer resources (small team).
- Must remain within the scope defined by business rules.

---

## 12. Initial / Known Risks

| # | Risk |
|:---:|---|
| ⚠️ 1 | Delays in client feedback may impact the timeline. |
| ⚠️ 2 | Google Calendar API integration may require additional configuration. |
| ⚠️ 3 | External payment apps may have limitations or fees. |
| ⚠️ 4 | Scope creep (additional features requested mid-project). |
| ⚠️ 5 | Limited time may restrict chatbot functionality. |

---

## 13. Project Success Criteria

The project is successful when:

- [ ] Clients can place catering orders online **without manual intervention**.
- [ ] Pricing and cost calculations are **accurate and automated**.
- [ ] The business receives **automated event notifications**.
- [ ] The website is **visually appealing, mobile friendly, and easy to navigate**.
- [ ] A **contract email is automatically generated** after the deposit.
- [ ] **Google Calendar events** are created reliably.
- [ ] The team delivers a **functional prototype/MVP** and **complete documentation**.

---

<sub>Popssibilities · Digital Modernization & Catering Management System · Project Charter</sub>
