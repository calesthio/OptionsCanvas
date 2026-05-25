class ChartTradingController {
    constructor() {
        this.state = this._initialState();
    }

    _initialState() {
        return {
            mode: 'idle',
            ready: false,
            valid: true,
            symbol: null,
            currentPrice: null,
            strike: null,
            dte: null,
            premium: null,
            contracts: 0,
            contractType: 'CALL',
            entryPrice: null,
            stopPrice: null,
            targetPrice: null,
            dragKind: null,
            dragStartPrice: null
        };
    }

    setTradingSnapshot(snapshot) {
        const strike = Number(snapshot?.strike);
        const dte = Number(snapshot?.dte);
        const currentPrice = Number(snapshot?.currentPrice);
        const premium = Number(snapshot?.premium);
        const contracts = Number(snapshot?.contracts);

        // If the source panel explicitly signals it is mid-load, hold not-ready
        // regardless of the data values (which can be stale carry-over from the
        // previous symbol until the new symbol's config + quote land).
        const panelReady = snapshot?.panelReady !== false;
        const ready = Boolean(
            panelReady &&
            snapshot?.symbol &&
            Number.isFinite(currentPrice) && currentPrice > 0 &&
            Number.isFinite(strike) && strike > 0 &&
            Number.isFinite(dte) && dte > 0 &&
            Number.isFinite(premium) && premium > 0 &&
            Number.isFinite(contracts) && contracts > 0
        );

        this.state = {
            ...this.state,
            symbol: snapshot?.symbol || null,
            currentPrice,
            strike,
            dte,
            premium,
            contracts,
            contractType: snapshot?.contractType || 'CALL',
            ready
        };

        if (!ready && this.state.mode !== 'idle') {
            this.state.mode = 'idle';
            this.state.dragKind = null;
            this.state.dragStartPrice = null;
        }
    }

    canSubmit() {
        return this.state.ready && this.state.mode !== 'submitting';
    }

    getState() {
        return { ...this.state };
    }

    startDrag(kind, price) {
        if (!this.state.ready) return false;
        this.state = {
            ...this.state,
            mode: kind === 'stop' ? 'dragging-stop' : 'dragging-target',
            dragKind: kind,
            dragStartPrice: Number(price),
            valid: true
        };
        return true;
    }

    moveDrag(price) {
        if (!this.state.dragKind) return false;
        const next = Number(price);
        if (!Number.isFinite(next)) return false;

        const updates = this.state.dragKind === 'stop'
            ? { stopPrice: next }
            : { targetPrice: next };

        this.state = {
            ...this.state,
            ...updates,
            valid: this.validateLevel(this.state.dragKind, next)
        };
        return true;
    }

    endDrag() {
        this.state = {
            ...this.state,
            mode: 'idle',
            dragKind: null,
            dragStartPrice: null
        };
    }

    validateLevel(kind, price) {
        if (!Number.isFinite(this.state.currentPrice)) return true;
        if (this.state.contractType === 'CALL') {
            return kind === 'stop'
                ? price < this.state.currentPrice
                : price > this.state.currentPrice;
        }
        return kind === 'stop'
            ? price > this.state.currentPrice
            : price < this.state.currentPrice;
    }

    reset() {
        this.state = this._initialState();
    }
}

if (typeof window !== 'undefined') {
    window.ChartTradingController = ChartTradingController;
}

export { ChartTradingController };
