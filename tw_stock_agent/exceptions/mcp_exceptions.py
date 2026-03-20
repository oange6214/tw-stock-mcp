"""
MCP protocol-related exception classes for Taiwan Stock Agent.

This module contains exceptions specific to MCP (Model Context Protocol)
operations, including validation, resource access, and tool execution errors.
"""

from typing import Any, Dict, Optional

from .base import ErrorCode, ErrorContext, ErrorSeverity, TwStockAgentError


class MCPError(TwStockAgentError):
    """Base exception for MCP protocol errors."""
    
    def __init__(
        self,
        message: str,
        mcp_method: Optional[str] = None,
        request_id: Optional[str] = None,
        error_code: ErrorCode = ErrorCode.MCP_ERROR,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[ErrorContext] = None,
        **kwargs
    ) -> None:
        if context is None:
            context = ErrorContext()
        if request_id:
            context.request_id = request_id
        
        super().__init__(
            message=message,
            error_code=error_code,
            severity=severity,
            context=context,
            mcp_method=mcp_method,
            **kwargs
        )
    
    def to_mcp_response(self) -> Dict[str, Any]:
        """Convert to MCP JSON-RPC error response format."""
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": self._get_mcp_error_code(),
                "message": self.message,
                "data": {
                    "error_code": self.error_code.value,
                    "severity": self.severity.value,
                    "correlation_id": self.context.correlation_id,
                    "timestamp": self.context.timestamp.isoformat(),
                    "suggestions": self.suggestions,
                }
            },
            "id": self.context.request_id
        }
    
    def _get_mcp_error_code(self) -> int:
        """Map internal error codes to MCP JSON-RPC error codes."""
        error_code_mapping = {
            ErrorCode.MCP_VALIDATION_ERROR: -32602,  # Invalid params
            ErrorCode.MCP_RESOURCE_ERROR: -32601,    # Method not found
            ErrorCode.MCP_TOOL_ERROR: -32603,        # Internal error
            ErrorCode.MCP_PROTOCOL_ERROR: -32600,    # Invalid request
        }
        return error_code_mapping.get(self.error_code, -32603)  # Default: Internal error


class MCPValidationError(MCPError):
    """Exception raised when MCP request validation fails."""
    
    def __init__(
        self,
        parameter: str,
        expected_type: Optional[str] = None,
        received_value: Optional[Any] = None,
        mcp_method: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Invalid parameter '{parameter}'"
            if expected_type:
                msg += f": expected {expected_type}"
            if received_value is not None:
                msg += f", received: {received_value}"
            message = msg
        
        super().__init__(
            message=message,
            mcp_method=mcp_method,
            error_code=ErrorCode.MCP_VALIDATION_ERROR,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Check parameter types and formats",
                "Refer to MCP tool documentation",
                "Validate input before sending request",
                "Use proper JSON schema validation"
            ],
            parameter=parameter,
            expected_type=expected_type,
            received_value=received_value,
            **kwargs
        )


class MCPResourceError(MCPError):
    """Exception raised when MCP resource access fails."""
    
    def __init__(
        self,
        resource_uri: str,
        operation: str = "access",
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Failed to {operation} resource: {resource_uri}"
        
        super().__init__(
            message=message,
            error_code=ErrorCode.MCP_RESOURCE_ERROR,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Check resource URI format",
                "Verify resource exists",
                "Check access permissions",
                "Try alternative resource path"
            ],
            resource_uri=resource_uri,
            operation=operation,
            **kwargs
        )


class MCPToolError(MCPError):
    """Exception raised when MCP tool execution fails."""
    
    def __init__(
        self,
        tool_name: str,
        operation: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = f"Tool execution failed: {tool_name}"
            if operation:
                msg += f" during {operation}"
            message = msg
        
        super().__init__(
            message=message,
            error_code=ErrorCode.MCP_TOOL_ERROR,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                "Check tool parameters",
                "Verify tool is properly configured",
                "Review tool documentation",
                "Check system resources and permissions"
            ],
            tool_name=tool_name,
            operation=operation,
            **kwargs
        )


class MCPProtocolError(MCPError):
    """Exception raised when MCP protocol violation occurs."""
    
    def __init__(
        self,
        protocol_version: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            msg = "MCP protocol error"
            if protocol_version:
                msg += f" (version {protocol_version})"
            message = msg
        
        super().__init__(
            message=message,
            error_code=ErrorCode.MCP_PROTOCOL_ERROR,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                "Check MCP protocol version compatibility",
                "Verify message format and structure",
                "Review MCP specification",
                "Update client/server to compatible version"
            ],
            protocol_version=protocol_version,
            **kwargs
        )


class MCPTimeoutError(MCPError):
    """Exception raised when MCP operation times out."""
    
    def __init__(
        self,
        operation: str,
        timeout_seconds: float,
        mcp_method: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"MCP {operation} timed out after {timeout_seconds} seconds"
        
        super().__init__(
            message=message,
            mcp_method=mcp_method,
            error_code=ErrorCode.API_TIMEOUT,
            severity=ErrorSeverity.MEDIUM,
            suggestions=[
                "Increase timeout duration",
                "Check network connectivity",
                "Optimize operation for better performance",
                "Break down large operations into smaller chunks"
            ],
            operation=operation,
            timeout_seconds=timeout_seconds,
            **kwargs
        )


class MCPAuthorizationError(MCPError):
    """Exception raised when MCP authorization fails."""
    
    def __init__(
        self,
        required_capability: str,
        mcp_method: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        if message is None:
            message = f"Insufficient permissions for MCP operation: requires '{required_capability}'"
        
        super().__init__(
            message=message,
            mcp_method=mcp_method,
            error_code=ErrorCode.API_AUTHENTICATION_ERROR,
            severity=ErrorSeverity.HIGH,
            suggestions=[
                "Check MCP client capabilities",
                "Verify authorization configuration",
                "Request necessary permissions",
                "Contact administrator for access"
            ],
            required_capability=required_capability,
            **kwargs
        )