import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# -----------------------------------------------------------------------------
# 1. APP CONFIG & INITIALIZATION
# -----------------------------------------------------------------------------
st.set_page_config(page_title="SSL Team Tracker & Analytics", layout="wide")
st.title("⚽ SSL Team Tracker & GM Dashboard")
st.markdown("---")

API_URL = "https://api.simulationsoccer.com/player/getAllPlayers?active=true"

ORG_MAPPING = {
    "CA Buenos Aires": {"Major": "CA Buenos Aires", "Minor": "Athênai F.C."},
    "Hollywood FC": {"Major": "Hollywood FC", "Minor": "F.C. Kaapstad"},
    "A.C. Romana": {"Major": "A.C. Romana", "Minor": "Inter London"},
    "Reykjavik United": {"Major": "Reykjavik United", "Minor": "North Shore United"},
    "Shanghai Dragons FC": {"Major": "Shanghai Dragons FC", "Minor": "Rapid Magyar SC"},
    "Xelajú Cósmico FC": {"Major": "Xelajú Cósmico FC", "Minor": "AF Masques Sacrés"},
    "Tokyo S.C.": {"Major": "Tokyo S.C.", "Minor": "Cairo City"},
    "CF Catalunya": {"Major": "CF Catalunya", "Minor": "Seoul MFC"},
    "União São Paulo": {"Major": "União São Paulo", "Minor": "AS Paris"},
    "Schwarzwälder FV": {"Major": "Schwarzwälder FV", "Minor": "Montréal United"},
    "CD Tenochtitlan": {"Major": "CD Tenochtitlan", "Minor": "Krung Thep FC"},
    "Liffeyside Celtic FC": {"Major": "Liffeyside Celtic FC", "Minor": "CS Rova Mpanjaka"}
}

TEAM_TO_ORG = {}
for org, teams in ORG_MAPPING.items():
    TEAM_TO_ORG[teams["Major"]] = {"org": org, "type": "Major"}
    TEAM_TO_ORG[teams["Minor"]] = {"org": org, "type": "Minor"}

POSITION_GROUPS = {
    "Attack": ["pos_st", "pos_lam", "pos_ram", "pos_cam"],
    "Midfield": ["pos_lm", "pos_cm", "pos_rm", "pos_cdm"],
    "Defense": ["pos_ld", "pos_lwb", "pos_rd", "pos_rwb", "pos_cd"],
    "Goalkeeper": ["pos_gk"]
}

CORE_ATTRIBUTES = [
    "acceleration", "agility", "balance", "jumping reach", "natural fitness", "pace", "stamina", "strength",
    "corners", "crossing", "dribbling", "finishing", "first touch", "free kick", "heading", "long shots",
    "long throws", "marking", "passing", "penalty taking", "tackling", "technique", "aggression", "anticipation",
    "bravery", "composure", "concentration", "decisions", "determination", "flair", "leadership", "off the ball",
    "positioning", "teamwork", "vision", "work rate"
]

# -----------------------------------------------------------------------------
# 2. DATA CACHING & PROCESSING
# -----------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_and_process_data():
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        st.error(f"Failed to fetch data from API: {e}")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df['tpe'] = pd.to_numeric(df['tpe'], errors='coerce').fillna(0)
    df['bankBalance'] = pd.to_numeric(df['bankBalance'], errors='coerce').fillna(0)
    
    # Map teams to Orgs
    df['assigned_org'] = df['team'].apply(lambda x: TEAM_TO_ORG.get(x, {}).get('org', 'Unknown'))
    df['league_tier'] = df['team'].apply(lambda x: TEAM_TO_ORG.get(x, {}).get('type', 'Unknown'))
    df = df[df['assigned_org'] != 'Unknown']
    
    # Extract season number for Age Tracking (e.g. "S13" -> 13.0)
    df['season_num'] = df['class'].astype(str).str.extract(r'(\d+)').astype(float)
    df['timesregressed'] = pd.to_numeric(df['timesregressed'], errors='coerce').fillna(0)
    
    return df

df_players = load_and_process_data()

if df_players.empty:
    st.warning("No data available to display.")
    st.stop()

# -----------------------------------------------------------------------------
# 3. GLOBAL SIDEBAR FILTERS
# -----------------------------------------------------------------------------
st.sidebar.header("Global Filters")

group_mode = st.sidebar.radio("Entity Grouping", ["Individual Teams", "Combined Franchise Orgs"], index=0)
group_col = 'team' if group_mode == "Individual Teams" else 'assigned_org'

tier_filter = st.sidebar.radio("League Tier", ["Both", "Majors Only", "Minors Only"], index=0)
roster_filter = st.sidebar.radio("Roster Inclusion", ["Top 11 Players (Starting XI)", "All Players"], index=0)
metric_toggle = st.sidebar.radio("Metric Display Mode", ["Average", "Total"], index=0)

if tier_filter == "Majors Only":
    df_active = df_players[df_players['league_tier'] == 'Major']
elif tier_filter == "Minors Only":
    df_active = df_players[df_players['league_tier'] == 'Minor']
else:
    df_active = df_players.copy()

if roster_filter == "Top 11 Players (Starting XI)":
    df_active = df_active.sort_values(by='tpe', ascending=False).groupby(group_col).head(11).reset_index(drop=True)

# -----------------------------------------------------------------------------
# 4. HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def build_positional_matrix(df_scope, metric, g_col):
    entities = df_scope[g_col].unique()
    data = []
    
    for e in entities:
        team_df = df_scope[df_scope[g_col] == e]
        team_stats = {"Entity Name": e}
        team_stats["Overall TPE"] = team_df['tpe'].mean() if metric == "Average" else team_df['tpe'].sum()
            
        for group, cols in POSITION_GROUPS.items():
            mask = team_df[cols].apply(lambda row: any(row >= 15), axis=1)
            group_df = team_df[mask]
            if not group_df.empty:
                team_stats[f"{group} TPE"] = group_df['tpe'].mean() if metric == "Average" else group_df['tpe'].sum()
            else:
                team_stats[f"{group} TPE"] = 0
        data.append(team_stats)
        
    res_df = pd.DataFrame(data)
    if not res_df.empty:
        res_df = res_df.sort_values(by="Overall TPE", ascending=False).reset_index(drop=True)
    return res_df

def calculate_positional_averages(df_scope, metric):
    pos_data = {}
    for group, columns in POSITION_GROUPS.items():
        mask = df_scope[columns].apply(lambda row: any(row >= 15), axis=1)
        matching_players = df_scope[mask]
        
        if not matching_players.empty:
            val = matching_players['tpe'].mean() if metric == "Average" else matching_players['tpe'].sum()
            pos_data[group] = {f"{metric} TPE": round(val, 1), "Count": len(matching_players)}
        else:
            pos_data[group] = {f"{metric} TPE": 0, "Count": 0}
    return pd.DataFrame(pos_data).T

# -----------------------------------------------------------------------------
# 5. MAIN INTERFACE TABS
# -----------------------------------------------------------------------------
tab_overview, tab_lifecycle, tab_matrix, tab_finance, tab_roster, tab_h2h = st.tabs([
    "📊 League Overview", 
    "⏳ Lifecycle Quadrants",
    "🧮 Positional TPE Matrix", 
    "💰 Financial Analysis",
    "📋 Team Deep Dive", 
    "⚔️ Head-to-Head"
])

# --- TAB 1: LEAGUE OVERVIEW ---
with tab_overview:
    st.header(f"League-Wide TPE Distribution ({roster_filter})")
    
    team_order = df_active.groupby(group_col)['tpe'].mean().sort_values(ascending=False).index.tolist()
    fig_scatter = px.scatter(
        df_active, x=group_col, y='tpe', color=group_col,
        hover_data=['name', 'team', 'class', 'position'],
        title=f"Player TPE Across {group_mode} (Sorted by Average TPE)",
        labels={group_col: 'Entity', 'tpe': 'Player TPE'},
        category_orders={group_col: team_order}
    )
    fig_scatter.update_layout(xaxis_tickangle=-45, showlegend=False)
    st.plotly_chart(fig_scatter, use_container_width=True)

# --- TAB 2: LIFECYCLE QUADRANTS ---
with tab_lifecycle:
    st.header(f"Team Lifecycle & Development ({roster_filter})")
    st.markdown("""
    This map shows exactly where each roster sits in its competitive window. 
    * **X-Axis:** Average Draft Class. (Reversed so older classes are on the right).
    * **Y-Axis:** Current TPE levels.
    """)
    
    # Calculate Team/Org Averages for TPE and Season Class
    lifecycle_df = df_active.groupby(group_col).agg(
        Avg_TPE=('tpe', 'mean' if metric_toggle == "Average" else 'sum'),
        Avg_Season=('season_num', 'mean')
    ).dropna().reset_index()

    if not lifecycle_df.empty:
        # Medians for the quadrant crosshairs
        med_tpe = lifecycle_df['Avg_TPE'].median()
        med_season = lifecycle_df['Avg_Season'].median()
        
        fig_quad = px.scatter(
            lifecycle_df, x='Avg_Season', y='Avg_TPE',
            text=group_col, color=group_col,
            title=f"Competitive Matrix ({metric_toggle} TPE vs. Roster Age)",
            labels={'Avg_Season': 'Average Draft Class (Lower Number = Older)', 'Avg_TPE': f'{metric_toggle} TPE'}
        )
        
        # Reverse X-Axis so older players (lower class numbers) are on the right
        fig_quad.update_xaxes(autorange="reversed")
        
        # Quadrant Lines
        fig_quad.add_hline(y=med_tpe, line_dash="dash", line_color="rgba(255,255,255,0.3)")
        fig_quad.add_vline(x=med_season, line_dash="dash", line_color="rgba(255,255,255,0.3)")
        
        # Quadrant Text Annotations
        # Because the X-axis is reversed, Left is higher season (Younger), Right is lower season (Older)
        fig_quad.add_annotation(x=0.05, y=0.95, xref="paper", yref="paper", text="🌟 Ideal (Young, High TPE)", showarrow=False, font=dict(color="#00cc96", size=14))
        fig_quad.add_annotation(x=0.95, y=0.95, xref="paper", yref="paper", text="⚔️ Competing (Old, High TPE)", showarrow=False, font=dict(color="#636efa", size=14))
        fig_quad.add_annotation(x=0.05, y=0.05, xref="paper", yref="paper", text="🏗️ Rebuilding (Young, Low TPE)", showarrow=False, font=dict(color="#ffa15a", size=14))
        fig_quad.add_annotation(x=0.95, y=0.05, xref="paper", yref="paper", text="⚠️ Danger Zone (Old, Low TPE)", showarrow=False, font=dict(color="#ef553b", size=14))
        
        fig_quad.update_traces(textposition='top center', marker=dict(size=12, line=dict(width=1, color='DarkSlateGrey')))
        fig_quad.update_layout(showlegend=False, height=600)
        
        st.plotly_chart(fig_quad, use_container_width=True)
    else:
        st.warning("Not enough draft class data to generate lifecycle matrix.")

# --- TAB 3: POSITIONAL MATRIX ---
with tab_matrix:
    st.header(f"Positional Breakdown ({metric_toggle} TPE)")
    st.markdown(f"*Currently viewing: {group_mode} | {tier_filter} | {roster_filter}*")
    
    matrix_df = build_positional_matrix(df_active, metric_toggle, group_col)
    
    st.dataframe(
        matrix_df.style.format(precision=1).background_gradient(cmap='viridis', subset=matrix_df.columns[1:]),
        use_container_width=True,
        hide_index=True
    )

# --- TAB 4: FINANCIALS ---
with tab_finance:
    st.header("Financial Overview")
    
    league_summary = df_active.groupby(group_col).agg(
        Total_Bank=('bankBalance', 'sum'),
        Avg_Bank=('bankBalance', 'mean')
    ).round(0).reset_index()

    fig_bank = px.bar(
        league_summary.sort_values(by="Total_Bank" if metric_toggle == "Total" else "Avg_Bank", ascending=False),
        x=group_col, y="Total_Bank" if metric_toggle == "Total" else "Avg_Bank",
        text="Total_Bank" if metric_toggle == "Total" else "Avg_Bank",
        title=f"Wealth Distribution ({metric_toggle} Bank Balance)",
        labels={"Total_Bank": "Total Combined Bank", "Avg_Bank": "Average Bank Balance", group_col: "Entity"}
    )
    fig_bank.update_traces(texttemplate='€%{text:,.0f}', textposition='outside')
    fig_bank.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig_bank, use_container_width=True)

# --- TAB 5: DETAILED ROSTER ANALYSIS ---
with tab_roster:
    st.header("Individual Roster Deep Dive")
    all_entities_filtered = sorted([t for t in df_active[group_col].unique() if t])
    selected_target = st.selectbox("Select Entity to Inspect", all_entities_filtered)
    
    df_team_specific = df_active[df_active[group_col] == selected_target]
    
    col_left, col_right = st.columns([1, 2])
    with col_left:
        st.subheader(f"Positional Depth ({metric_toggle})")
        pos_df = calculate_positional_averages(df_team_specific, metric_toggle)
        st.dataframe(pos_df, use_container_width=True)
        
        # Mini Age Metric
        avg_season = df_team_specific['season_num'].mean()
        regressing = len(df_team_specific[df_team_specific['timesregressed'] > 0])
        st.metric("Avg Draft Class", f"S{avg_season:.1f}")
        st.metric("Players in Regression", regressing, delta="Danger" if regressing >= 3 else "Stable", delta_color="inverse")
        
    with col_right:
        st.subheader("Core Attribute Profile (Roster Averages)")
        attr_means = df_team_specific[CORE_ATTRIBUTES].mean().round(2).reset_index()
        attr_means.columns = ['Attribute', 'Average Value']
        
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(r=attr_means['Average Value'], theta=attr_means['Attribute'], fill='toself', name=selected_target))
        fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 20])), showlegend=False, margin=dict(l=40, r=40, t=40, b=40))
        st.plotly_chart(fig_radar, use_container_width=True)

    st.subheader(f"Active Players ({roster_filter})")
    st.dataframe(
        df_team_specific[['name', 'team', 'class', 'position', 'tpe', 'bankBalance', 'timesregressed']],
        use_container_width=True,
        hide_index=True
    )

# --- TAB 6: HEAD-TO-HEAD ---
with tab_h2h:
    st.header(f"⚔️ Tactical Matchup ({metric_toggle})")
    
    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        team_a = st.selectbox("Select Blue Corner", all_entities_filtered, index=0)
    with col_sel2:
        team_b = st.selectbox("Select Red Corner", all_entities_filtered, index=min(1, len(all_entities_filtered)-1))
        
    df_a = df_active[df_active[group_col] == team_a]
    df_b = df_active[df_active[group_col] == team_b]
    
    pos_a = calculate_positional_averages(df_a, metric_toggle)
    pos_b = calculate_positional_averages(df_b, metric_toggle)
    
    comparison_df = pd.DataFrame({
        f"{team_a} {metric_toggle} TPE": pos_a[f"{metric_toggle} TPE"],
        f"{team_a} Count": pos_a["Count"],
        f"{team_b} {metric_toggle} TPE": pos_b[f"{metric_toggle} TPE"],
        f"{team_b} Count": pos_b["Count"]
    })
    
    st.subheader("Side-by-Side Positional Breakdown")
    st.dataframe(comparison_df, use_container_width=True)
    
    st.subheader("Direct Attribute Overlay")
    attr_a = df_a[CORE_ATTRIBUTES].mean().round(2)
    attr_b = df_b[CORE_ATTRIBUTES].mean().round(2)
    
    fig_h2h_radar = go.Figure()
    fig_h2h_radar.add_trace(go.Scatterpolar(r=attr_a.values, theta=CORE_ATTRIBUTES, fill='toself', name=team_a, fillcolor='rgba(31, 119, 180, 0.2)', line=dict(color='blue')))
    fig_h2h_radar.add_trace(go.Scatterpolar(r=attr_b.values, theta=CORE_ATTRIBUTES, fill='toself', name=team_b, fillcolor='rgba(214, 39, 40, 0.2)', line=dict(color='red')))
    
    fig_h2h_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 20])))
    st.plotly_chart(fig_h2h_radar, use_container_width=True)