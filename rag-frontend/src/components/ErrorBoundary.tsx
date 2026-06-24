import { Component, type ErrorInfo, type ReactNode } from "react"

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error:", error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="max-w-lg mx-auto mt-24 rounded-md border border-destructive/20 bg-destructive/10 p-6 text-center">
          <h2 className="font-semibold text-destructive">Something went wrong</h2>
          <p className="mt-2 text-sm text-muted-foreground break-words">{this.state.error.message}</p>
          <button
            onClick={() => this.setState({ error: null })}
            className="mt-4 text-sm text-primary hover:underline"
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
