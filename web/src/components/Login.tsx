"use client";

import { useState } from "react";
import { login, setToken, type User } from "@/lib/api";
import Icon from "./Icon";
import styles from "./Login.module.css";

const DEMOS = [
  { type: "学生用户", user: "student", pass: "student123", desc: "制度问答、可信引用与个人记忆", icon: "chat" as const },
  { type: "部门管理员", user: "jwc_admin", pass: "admin123", desc: "部门文档、审核与局部进化", icon: "building" as const },
  { type: "超级管理员", user: "admin", pass: "admin123", desc: "全局治理、Loop 与策略实验", icon: "shield" as const },
];

export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(""); setBusy(true);
    try {
      const res = await login(username.trim(), password);
      setToken(res.token); onLogin(res.user);
    } catch (err) { setError(String(err instanceof Error ? err.message : err)); }
    finally { setBusy(false); }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.ambientOne} /><div className={styles.ambientTwo} />
      <section className={styles.story}>
        <div className={styles.wordmark}><span className={styles.seal}>文</span><span>文枢 WENSHU</span></div>
        <div className={styles.eyebrow}><span /> TRUSTED KNOWLEDGE ORCHESTRATION</div>
        <h1>让制度知识<br />有据可循，持续进化。</h1>
        <p className={styles.lead}>连接跨部门事实、记忆与反馈，让每一次问答都可追溯，让每一次纠正都改变下一轮行为。</p>
        <div className={styles.arch}>
          {[
            ["database", "事实平面", "版本化制度与引用"],
            ["brain", "五层记忆", "情景、用户、组织、学习"],
            ["loop", "进化闭环", "Observe → Reflect → Adapt"],
          ].map(([icon, title, text]) => <div key={title} className={styles.archItem}>
            <span className={styles.archIcon}><Icon name={icon as "database"} size={19} /></span>
            <div><b>{title}</b><small>{text}</small></div>
          </div>)}
        </div>
        <div className={styles.trust}><Icon name="shield" size={16} /> Python 控制平面 · pi Agent 执行引擎 · 全链路审计</div>
      </section>

      <section className={styles.loginSide}>
        <form className={styles.card} onSubmit={submit}>
          <div className={styles.mobileBrand}><span className={styles.seal}>文</span> 文枢</div>
          <div className={styles.cardHead}>
            <span className={styles.kicker}>WELCOME BACK</span>
            <h2>进入知识中枢</h2>
            <p>系统会依据账号权限进入对应工作台</p>
          </div>
          <label className={styles.field}><span>账号</span><div className={styles.inputWrap}><Icon name="agent" size={17}/><input value={username} onChange={e => setUsername(e.target.value)} placeholder="请输入账号" autoFocus /></div></label>
          <label className={styles.field}><span>密码</span><div className={styles.inputWrap}><Icon name="shield" size={17}/><input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="请输入密码" /></div></label>
          {error && <div className={styles.error}>{error}</div>}
          <button className={styles.submit} type="submit" disabled={busy}>{busy ? <><span className={styles.spinner}/>正在验证</> : <>安全登录 <Icon name="arrow" size={17}/></>}</button>
          <div className={styles.divider}><span>演示身份快速进入</span></div>
          <div className={styles.demoList}>{DEMOS.map(d => <button key={d.user} type="button" className={styles.demo} onClick={() => { setUsername(d.user); setPassword(d.pass); setError(""); }}>
            <span className={styles.demoIcon}><Icon name={d.icon} size={17}/></span><span><b>{d.type}</b><small>{d.desc}</small></span><code>{d.user}</code>
          </button>)}</div>
          <div className={styles.security}><Icon name="shield" size={14}/> 本地演示环境 · Token 带有效期 · 操作按角色隔离</div>
        </form>
      </section>
    </div>
  );
}
